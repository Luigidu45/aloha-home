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

from dimos.experimental.domestic_assistance.contracts import Intervention
from dimos.experimental.domestic_assistance.metrics import (
    aggregate_metrics,
    derive_episode_metrics,
)


def test_metrics_are_derived_without_modifying_the_journal(make_rig):
    rig = make_rig()
    rig.finish()
    before = rig.journal.path.read_bytes()

    metrics = derive_episode_metrics(rig.journal.path)

    assert rig.journal.path.read_bytes() == before
    assert metrics.task_id == "reading"
    assert metrics.mission_success is True
    assert metrics.autonomous_success is True
    assert metrics.decisions == 6
    assert metrics.executed_decisions == 6
    assert metrics.rejected_preconditions == 0
    assert metrics.repeated_decisions == 0
    assert metrics.executor_outcomes.success == 6
    assert metrics.verification_outcomes.success == 6


def test_aggregate_metrics_separates_mission_and_autonomous_success(make_rig):
    autonomous = make_rig()
    autonomous.finish()
    assisted = make_rig()
    assisted.runner.record_intervention(
        Intervention(
            kind="VERBAL",
            occurred_at=assisted.clock.time(),
            detail="operator supplied a hint",
        )
    )
    assisted.finish()

    metrics = aggregate_metrics((autonomous.journal.path, assisted.journal.path))

    assert metrics.episodes == 2
    assert metrics.auditable_valid_episodes == 2
    assert metrics.mission_successes == 2
    assert metrics.autonomous_successes == 1
    assert metrics.mission_success_rate == 1.0
    assert metrics.autonomous_success_rate == 0.5
    assert metrics.total_interventions == 1
    assert metrics.termination_counts == {"SUCCESS": 2}
