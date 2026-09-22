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

"""F7 rejects unsafe data and discards queued/late actions without hardware."""

from dataclasses import replace
from pathlib import Path
import threading

import numpy as np
import pytest

from dimos.experimental.household_assistant.act_adapter import ACTDryRunAdapter, DryRunReceiver
from dimos.experimental.household_assistant.act_contracts import (
    load_act_profile,
    synthetic_observation,
)
from dimos.experimental.household_assistant.act_process import LeRobotProcess
from dimos.experimental.household_assistant.contracts import ActionProposal
from dimos.experimental.household_assistant.mission_contracts import ExecutorCommand


@pytest.fixture
def act_profile():
    return load_act_profile(Path(__file__).parent / "configs/act_act_pick_table.json")


@pytest.fixture
def act_setup(act_profile, mocker):
    observation = synthetic_observation(act_profile, 0, 0, at=100.0)
    policy = mocker.Mock()
    policy.profile = act_profile
    policy.predict.return_value = np.tile(observation.state + 0.01, (act_profile.chunk_size, 1))
    receiver = DryRunReceiver()
    adapter = ACTDryRunAdapter(policy, receiver)
    release = threading.Event()
    command = ExecutorCommand(
        kind="start",
        executor_id=act_profile.executor_id,
        clock_id="unix",
        issued_at=100,
        action=ActionProposal(
            id="act_a",
            request_id="request_a",
            skill_id=act_profile.skill_id,
            arm="right",
            destination_id="mesa_sala",
            object_id="bottle_01",
        ),
    )
    try:
        yield adapter, policy, receiver, observation, command, release
    finally:
        release.set()
        adapter.close()


def complete_prediction(adapter):
    # Synchronize the owned future; no fixed sleeps or hardware/model dependencies.
    adapter._future.result(timeout=2)


def fresh(observation, at):
    return replace(
        observation, captured_at=at, camera_times={name: at for name in observation.images}
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing_camera",
        "wrong_dimension",
        "wrong_order",
        "stale",
        "future",
        "skew",
        "nonfinite",
        "image_size",
        "moving_base",
        "moving_elevator",
        "moving_other_arm",
        "physical_origin",
    ],
)
def test_invalid_observation_never_admits_or_sends(act_setup, change):
    adapter, policy, receiver, observation, command, _ = act_setup
    changes = {
        "missing_camera": {
            "images": {k: v for k, v in observation.images.items() if k != "left_wrist_rgb"}
        },
        "wrong_dimension": {"state": np.zeros(7, dtype=np.float32)},
        "wrong_order": {"axes": tuple(reversed(observation.axes))},
        "stale": {"captured_at": 99.0},
        "future": {"captured_at": 101.0},
        "skew": {"camera_times": {k: 99.9 for k in observation.images}},
        "nonfinite": {"state": np.full(6, np.nan, dtype=np.float32)},
        "image_size": {"images": {k: v[:20] for k, v in observation.images.items()}},
        "moving_base": {"base_stopped": False},
        "moving_elevator": {"elevator_stopped": False},
        "moving_other_arm": {"other_arm_stopped": False},
        "physical_origin": {"provenance": "physical"},
    }
    with pytest.raises(ValueError):
        adapter.accept(command, replace(observation, **changes[change]), now=100)
    policy.predict.assert_not_called()
    assert receiver.commands == []


def test_rate_limit_and_cancel_clear_remaining_actions(act_setup):
    adapter, _, receiver, observation, command, _ = act_setup
    adapter.accept(command, observation, now=100)
    adapter.tick(observation, now=100)
    complete_prediction(adapter)
    adapter.tick(fresh(observation, 100.01), now=100.01)
    adapter.tick(fresh(observation, 100.02), now=100.02)
    assert len(receiver.commands) == 1
    adapter.accept(command.model_copy(update={"kind": "stop"}), observation, now=100.03)
    adapter.tick(fresh(observation, 100.2), now=100.2)
    assert len(receiver.commands) == 1
    assert receiver.stopped
    assert adapter.results[-1].stage == "stopped"
    with pytest.raises(ValueError, match="replay"):
        adapter.accept(command, observation, now=100)


def test_late_prediction_after_cancel_cannot_move_or_leak_into_next_action(act_setup):
    adapter, policy, receiver, observation, command, release = act_setup
    started = threading.Event()

    def blocked(_):
        started.set()
        assert release.wait(timeout=2)
        return np.tile(observation.state + 0.01, (4, 1))

    policy.predict.side_effect = blocked
    adapter.accept(command, observation, now=100)
    adapter.tick(observation, now=100)
    assert started.wait(timeout=2)
    adapter.cancel(now=100.01)
    assert adapter.results[-1].stage == "stopped"
    assert receiver.commands == []
    release.set()
    complete_prediction(adapter)
    new_command = command.model_copy(
        update={"action": command.action.model_copy(update={"id": "act_b"})}
    )
    adapter.accept(new_command, fresh(observation, 100.02), now=100.02)
    adapter.tick(fresh(observation, 100.03), now=100.03)
    assert receiver.commands == []
    adapter.tick(fresh(observation, 100.04), now=100.04)
    complete_prediction(adapter)
    adapter.tick(fresh(observation, 100.05), now=100.05)
    assert [c[0] for c in receiver.commands] == ["act_b"]


@pytest.mark.parametrize("change", ["missing_camera", "stale", "expired_prediction"])
def test_freshness_checked_again_before_each_dispatch(act_setup, change):
    adapter, _, receiver, observation, command, _ = act_setup
    adapter.accept(command, observation, now=100)
    adapter.tick(observation, now=100)
    complete_prediction(adapter)
    now = 100.6 if change == "expired_prediction" else 100.05
    current = fresh(observation, now)
    if change == "missing_camera":
        current = replace(current, images={})
    elif change == "stale":
        current = replace(current, captured_at=99)
    adapter.tick(current, now=now)
    assert receiver.commands == []
    assert receiver.stopped
    assert adapter.results[-1].stage == "failed"


@pytest.mark.parametrize(
    "chunk", [np.zeros((4, 7)), np.full((4, 6), np.nan), np.full((4, 6), 2.0), np.full((4, 6), 0.8)]
)
def test_invalid_prediction_stops_without_sending(act_setup, chunk):
    adapter, policy, receiver, observation, command, _ = act_setup
    policy.predict.return_value = chunk
    adapter.accept(command, observation, now=100)
    adapter.tick(observation, now=100)
    complete_prediction(adapter)
    adapter.tick(fresh(observation, 100.01), now=100.01)
    assert receiver.commands == []
    assert adapter.results[-1].stage == "failed"


def test_motion_end_is_not_task_success(act_setup):
    adapter, _, receiver, observation, command, _ = act_setup
    adapter.accept(command, observation, now=100)
    adapter.tick(observation, now=100)
    complete_prediction(adapter)
    with pytest.raises(RuntimeError):
        adapter.finish_motion(now=100)
    adapter.tick(fresh(observation, 100.01), now=100.01)
    adapter.tick(fresh(observation, 100.12), now=100.12)
    adapter.finish_motion(now=100.13)
    assert len(receiver.commands) == 2
    assert adapter.results[-1].stage == "finished"
    assert "independent_F4_verification" in adapter.results[-1].detail


def test_other_skill_checkpoint_rejected_before_process_start(act_profile, tmp_path, mocker):
    (tmp_path / "household_profile.json").write_text(
        act_profile.model_copy(
            update={"skill_id": "place_on_table", "executor_id": "act_place"}
        ).model_dump_json()
    )
    start = mocker.patch("dimos.experimental.household_assistant.act_process.subprocess.Popen")
    with pytest.raises(ValueError, match="checkpoint/profile"):
        LeRobotProcess(
            python=Path("unused"),
            source=tmp_path,
            deps=tmp_path,
            profile_path=Path(__file__).parent / "configs/act_act_pick_table.json",
            checkpoint=tmp_path,
            log=tmp_path / "log",
        )
    start.assert_not_called()
