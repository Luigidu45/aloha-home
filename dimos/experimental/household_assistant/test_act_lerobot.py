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

"""Run inside the optional LeRobot environment; no models, data or Hub downloads."""

from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip(
    "lerobot", reason="F7 integration tests run in the separate LeRobot environment"
)

from lerobot.datasets.lerobot_dataset import LeRobotDataset

from dimos.experimental.household_assistant.act_contracts import (
    load_act_profile,
    synthetic_observation,
)
from dimos.experimental.household_assistant.act_lerobot import ACTRecorder, train_stats


@pytest.fixture
def recorder(tmp_path):
    profile = load_act_profile(Path(__file__).parent / "configs/act_act_pick_table.json")
    capture = ACTRecorder(tmp_path / "data", profile)
    try:
        yield capture
    finally:
        capture.close()


def add_episode(recorder, offset=0.0):
    for frame in range(4):
        observation = synthetic_observation(recorder.profile, frame, 0, at=100 + frame / 10)
        observation = replace(observation, state=observation.state + np.float32(offset))
        recorder.add(observation, observation.state + 0.01, issued_at=observation.captured_at)


def test_export_reload_keeps_three_cameras_feedback_command_and_timestamps(recorder):
    add_episode(recorder)
    recorder.save_episode(session_id="session_1", split="train", reset_id="reset_1")
    recorder.close()
    data = LeRobotDataset("local/act_pick_table", root=recorder.root)
    assert len(data) == 4
    first = data[0]
    np.testing.assert_allclose(
        first["action"].numpy() - first["observation.state"].numpy(), 0.01, atol=1e-7
    )
    assert first["capture_times"].tolist() == [100] * 5
    assert all(
        first[f"observation.images.{name}"].shape == (3, 128, 128)
        for name in recorder.profile.cameras
    )
    manifest = json.loads((recorder.root / "meta/household.json").read_text())
    assert manifest["episodes"][0]["session_id"] == "session_1"
    assert manifest["profile"]["provenance"] == "artificial_pipeline_only"


def test_session_cannot_leak_into_holdout(recorder):
    add_episode(recorder)
    recorder.save_episode(session_id="session_1", split="train", reset_id="reset_1")
    add_episode(recorder)
    with pytest.raises(ValueError, match="leakage"):
        recorder.save_episode(session_id="session_1", split="test", reset_id="reset_2")
    recorder.discard_episode()
    assert len(recorder.episodes) == 1


def test_capture_gap_and_discard_do_not_create_a_valid_episode(recorder):
    observation = synthetic_observation(recorder.profile, 0, 0, at=100)
    recorder.add(observation, observation.state + 0.01, issued_at=100)
    late = synthetic_observation(recorder.profile, 1, 0, at=100.3)
    with pytest.raises(ValueError, match="gap/jitter"):
        recorder.add(late, late.state + 0.01, issued_at=100.3)
    with pytest.raises(ValueError, match="shorter"):
        recorder.save_episode(session_id="session_1", split="train", reset_id="reset_1")
    recorder.discard_episode()
    add_episode(recorder)
    recorder.save_episode(session_id="session_2", split="train", reset_id="reset_2")
    assert recorder.episodes[0]["frames"] == 4
    assert recorder.episodes[0]["session_id"] == "session_2"


@pytest.mark.parametrize("change", ["missing_camera", "stale"])
def test_invalid_capture_rejected_before_dataset_write(recorder, change):
    observation = synthetic_observation(recorder.profile, 0, 0, at=100)
    bad = (
        replace(observation, images={})
        if change == "missing_camera"
        else replace(observation, captured_at=99)
    )
    with pytest.raises(ValueError):
        recorder.add(bad, observation.state + 0.01, issued_at=100)
    assert recorder.episodes == []


def test_normalization_excludes_validation_session(recorder):
    add_episode(recorder)
    recorder.save_episode(session_id="train_day", split="train", reset_id="reset_1")
    add_episode(recorder, offset=0.5)
    recorder.save_episode(session_id="validation_day", split="validation", reset_id="reset_2")
    recorder.close()
    train = LeRobotDataset("local/act_pick_table", root=recorder.root, episodes=[0])
    stats = train_stats(train, recorder.profile)
    expected = np.stack(
        [synthetic_observation(recorder.profile, i, 0, at=100 + i / 10).state for i in range(4)]
    ).mean(axis=0)
    np.testing.assert_allclose(stats["observation.state"]["mean"], expected, atol=1e-7)
    assert np.max(stats["observation.state"]["mean"]) < 0.1
