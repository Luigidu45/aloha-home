# Copyright 2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json

import pytest

from dimos.experimental.domestic_assistance.rollouts import EpisodeJournal, audit_episode


def test_episode_file_cannot_be_overwritten(make_rig):
    rig = make_rig()
    original = rig.journal.path.read_bytes()
    with pytest.raises(FileExistsError):
        EpisodeJournal(rig.journal.path.parent, rig.journal.path.stem)
    assert rig.journal.path.read_bytes() == original


def test_truncated_result_is_reported_without_success_label(make_rig):
    rig = make_rig()
    rig.runner.tick()
    rig.journal.close()
    with rig.journal.path.open("a") as stream:
        stream.write('{"partial":')
    report = audit_episode(rig.journal.path)
    assert report.complete is False
    assert "line 3: malformed event" in report.errors
    assert "unfinished decision" in report.errors


def test_auditor_detects_missing_evidence_and_corrupted_sequence(make_rig):
    rig = make_rig()
    rig.finish()
    rig.journal.close()
    rows = [json.loads(line) for line in rig.journal.path.read_text().splitlines()]
    rows[1]["sequence"] = 99
    rows[1]["body"]["observation"]["keyframes"] = [
        {
            "camera": "top",
            "path": "missing.jpg",
            "captured_at": rows[1]["body"]["observation"]["captured_at"],
        }
    ]
    rig.journal.path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    report = audit_episode(rig.journal.path)
    assert report.complete is False
    assert "line 2: invalid sequence or elapsed time" in report.errors
    assert "missing keyframe: missing.jpg" in report.errors


def test_auditor_rejects_fabricated_terminal_success(make_rig):
    rig = make_rig(faults={1: "failed", 2: "failed"})
    rig.finish()
    rig.journal.close()
    rows = [json.loads(line) for line in rig.journal.path.read_text().splitlines()]
    rows[-1]["body"]["summary"]["reason"] = "SUCCESS"
    rows[-1]["body"]["summary"]["autonomous_success"] = True
    rig.journal.path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    report = audit_episode(rig.journal.path)
    assert "mission success without verified goals" in report.errors
    assert report.autonomous_success is None
