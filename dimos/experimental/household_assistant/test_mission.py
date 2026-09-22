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

"""Behavioral F4 acceptance with explicit clocks and the artificial executor boundary."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from dimos.experimental.household_assistant.contracts import (
    ActionProposal,
    Origin,
    Predicate,
    Verdict,
)
from dimos.experimental.household_assistant.mission import MissionManager
from dimos.experimental.household_assistant.mission_contracts import ExecutorBinding, ExecutorResult
from dimos.experimental.household_assistant.mission_sequence import MissionSequence
from dimos.experimental.household_assistant.mission_simulation import (
    ArtificialMissionExecutor,
    simulation_bindings,
)


@pytest.fixture
def mission(pilot, request_a):
    manager = MissionManager(
        pilot,
        simulation_bindings(pilot),
        clock_id="test",
        stop_timeout_s=1,
        verification_timeout_s=0.5,
    )
    driver = ArtificialMissionExecutor(manager)
    driver.step(now=100)
    manager.submit(request_a, now=100)
    return manager, driver, MissionSequence(manager, request_a)


def drive(mission, predicate, *, start=100.0, steps=2000):
    manager, driver, sequence = mission
    for i in range(1, steps + 1):
        now = round(start + i * 0.1, 6)
        frame = driver.step(now=now)
        sequence.advance(frame, now=now)
        if predicate(manager.snapshot()):
            return now
    pytest.fail(f"mission did not reach expected state: {manager.snapshot()}")


def test_nominal_verifies_full_transfer_and_preserves_test_provenance(mission):
    manager, driver, _ = mission
    drive(mission, lambda s: s.state == "succeeded")
    result = manager.snapshot()
    assert result.completed_actions == (
        "navigate_to",
        "observe_at",
        "align_at",
        "pick_bottle_from_table",
        "prepare_transport",
        "navigate_to",
        "align_at",
        "place_on_table",
    )
    assert result.held_object_id is None
    assert result.verification.verdict == Verdict.SUCCESS
    assert {e.origin for e in result.verification.evidence} == {Origin.TEST}
    assert driver.placed == "bottle_01"
    assert manager.completed_execution().recorded_at < min(
        e.captured_at for e in result.verification.evidence
    )


@pytest.mark.parametrize(
    ("scenario", "state", "reason"),
    [
        ("absent", "asking", "not_found"),
        ("ambiguous", "asking", "ambiguous"),
        ("unknown", "asking", "unknown"),
        ("grasp_failure", "failed", "postconditions_false"),
        ("unverified_grasp", "failed", "postconditions_inconclusive"),
        ("timeout", "failed", "action_timeout"),
        ("retention_loss", "failed", "transport_retention_or_posture_unconfirmed"),
        ("posture_loss", "failed", "transport_retention_or_posture_unconfirmed"),
        ("occupied", "asking", "admission_requires_clarification"),
        ("disconnect", "stop_unconfirmed", "sensor_disconnect"),
    ],
)
def test_failures_never_become_delivery_success(mission, scenario, state, reason):
    manager, driver, _ = mission
    driver.scenario = scenario
    drive(mission, lambda s: s.state in {"asking", "failed", "stop_unconfirmed"})
    assert manager.snapshot().state == state
    assert reason in manager.snapshot().reason
    assert driver.placed is None
    assert manager.completed_execution() is None


def test_unknown_search_has_finite_observation_budget(mission):
    manager, driver, _ = mission
    driver.scenario = "unknown"
    drive(mission, lambda s: s.state == "asking")
    assert manager.snapshot().completed_actions.count("observe_at") == 2
    assert not any(c.executor_id == "act_pick_table" for c in driver.dispatched)


def test_request_and_action_retries_do_not_duplicate_dispatch(mission, request_a):
    manager, driver, _ = mission
    action = ActionProposal(
        id="dedup",
        request_id=request_a.id,
        skill_id="navigate_to",
        destination_id=request_a.source_id,
    )
    revision = manager.snapshot().revision
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: manager.propose(action, expected_revision=revision, now=100), range(8)
            )
        )
    assert all(r.action == action for r in results)
    assert len(manager.take_commands()) == 1
    assert manager.submit(request_a, now=100).request_id == request_a.id
    with pytest.raises(ValueError, match="different payload"):
        manager.submit(request_a.model_copy(update={"instruction": "Otro texto"}), now=100)
    with pytest.raises(ValueError, match="different payload"):
        manager.propose(
            action.model_copy(update={"destination_id": request_a.destination_id}),
            expected_revision=revision,
            now=100,
        )
    assert not driver.dispatched


def test_cancel_before_adapter_start_removes_pending_start(mission, request_a):
    manager, _, sequence = mission
    sequence.advance(mission[1].latest_frame, now=100)
    before = manager.snapshot().action
    manager.cancel(now=100.1)
    commands = manager.take_commands()
    assert [c.kind for c in commands] == ["stop"]
    assert commands[0].action == before
    assert manager.snapshot().state == "stopping"
    with pytest.raises(RuntimeError, match="active"):
        manager.submit(request_a.model_copy(update={"id": "second"}), now=100.1)


def test_late_motor_success_cannot_override_cancellation(mission):
    manager, driver, _ = mission
    now = drive(mission, lambda s: s.state == "navigating")
    action = manager.snapshot().action
    manager.cancel(now=now)
    manager.receive(
        ExecutorResult(
            executor_id="navigation",
            action_id=action.id,
            stage="finished",
            recorded_at=now,
            clock_id="test",
            detail="late_success",
        ),
        now=now,
    )
    assert manager.snapshot().state == "stopping"
    driver.step(now=now + 0.1)
    assert manager.snapshot().state == "cancelled"
    assert not manager.snapshot().completed_actions


def test_stop_ack_without_fresh_sensor_stop_keeps_admission_locked(mission, request_a):
    manager, driver, _ = mission
    now = drive(mission, lambda s: s.state == "navigating")
    action = manager.snapshot().action
    manager.cancel(now=now)
    manager.receive(
        ExecutorResult(
            executor_id="navigation",
            action_id=action.id,
            stage="stopped",
            recorded_at=now,
            clock_id="test",
            detail="queue_cleared",
        ),
        now=now,
    )
    manager.tick(now=now + 2)
    assert manager.snapshot().state == "stop_unconfirmed"
    with pytest.raises(RuntimeError, match="active"):
        manager.submit(request_a.model_copy(update={"id": "other"}), now=now + 2)
    driver.step(now=now + 2.1)
    assert manager.snapshot().state == "cancelled"
    assert manager.snapshot().stop_confirmed_at > manager.snapshot().stop_requested_at


def test_finished_pick_waits_for_later_held_evidence(mission):
    manager, _, _ = mission
    now = drive(
        mission, lambda s: s.state == "verifying" and s.action.skill_id == "pick_bottle_from_table"
    )
    assert manager.snapshot().held_object_id is None
    assert manager.snapshot().verification.verdict == Verdict.UNKNOWN
    drive(mission, lambda s: s.held_object_id == "bottle_01", start=now)
    assert manager.snapshot().held_object_id == "bottle_01"


def test_pause_reprepares_changed_payload_posture_and_never_replays_interrupted_action(mission):
    manager, driver, _ = mission
    now = drive(mission, lambda s: s.state == "navigating" and s.held_object_id == "bottle_01")
    interrupted = manager.snapshot().action.id
    # Simulate a posture change while stopping: resume must require fresh stowing.
    driver.loaded = False
    manager.cancel(now=now, pause=True)
    driver.step(now=now + 0.1)
    assert manager.snapshot().state == "paused"
    manager.resume(now=now + 0.1)
    assert manager.snapshot().completed_actions == ()
    assert manager.snapshot().held_object_id == "bottle_01"
    drive(mission, lambda s: s.state == "succeeded", start=now + 0.1)
    assert sum(c.action.id == interrupted for c in driver.dispatched) <= 1
    assert sum(c.action.skill_id == "prepare_transport" for c in driver.dispatched) == 2


def test_old_revision_and_missing_camera_reject_pickup(mission, request_a):
    manager, driver, _ = mission
    now = drive(mission, lambda s: "align_at" in s.completed_actions)
    action = ActionProposal(
        id="manual_pick",
        request_id=request_a.id,
        skill_id="pick_bottle_from_table",
        destination_id=request_a.source_id,
        object_id="bottle_01",
        arm="right",
    )
    # The automatic baseline may already have dispatched pickup; isolate the proposal boundary
    # using a fresh manager with the same observed, stopped scene.
    other = MissionManager(manager.pilot, simulation_bindings(manager.pilot), clock_id="test")
    frame = driver.latest_frame
    other.update_world(frame, now=now)
    other.submit(request_a, now=now)
    other.select_target("bottle_01", expected_revision=frame.revision, now=now)
    with pytest.raises(ValueError, match="scene changed"):
        other.propose(action, expected_revision=frame.revision - 1, now=now)
    other.update_world(
        frame.model_copy(update={"captured_at": now + 0.1, "cameras": {}}), now=now + 0.1
    )
    with pytest.raises(ValueError, match="cameras"):
        other.propose(action, expected_revision=frame.revision, now=now + 0.1)
    assert other.take_commands() == ()


def test_stale_hold_stops_transport_even_with_fresh_envelope(mission):
    manager, driver, _ = mission
    now = drive(mission, lambda s: s.state == "navigating" and s.held_object_id == "bottle_01")
    frame = driver.latest_frame
    observations = tuple(
        o.model_copy(
            update={
                "evidence": tuple(
                    e.model_copy(update={"captured_at": now - 10}) for e in o.evidence
                )
            }
        )
        if o.key.predicate == Predicate.HELD
        else o
        for o in frame.observations
    )
    manager.update_world(
        frame.model_copy(update={"captured_at": now + 0.1, "observations": observations}),
        now=now + 0.1,
    )
    assert manager.snapshot().state == "stopping"
    assert manager.snapshot().reason == "transport_retention_or_posture_unconfirmed"


def test_physical_or_mislabeled_artificial_binding_rejected(pilot):
    binding = simulation_bindings(pilot)[0]
    with pytest.raises(ValueError, match="F4 accepts"):
        MissionManager(pilot, [binding.model_copy(update={"origin": Origin.PHYSICAL})])
    with pytest.raises(ValueError, match="F4 accepts"):
        MissionManager(
            pilot,
            [
                ExecutorBinding(
                    id=binding.id,
                    operations=binding.operations,
                    origin=Origin.TEST,
                    artificial=False,
                )
            ],
        )
