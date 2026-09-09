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

import pytest

from dimos.experimental.domestic_assistance.contracts import (
    Action,
    BehaviorMetadata,
    Candidate,
    Decision,
    DispatchStatus,
    ExecutionResult,
    GripperState,
    Intervention,
    Limits,
    Origin,
    Outcome,
)
from dimos.experimental.domestic_assistance.rollouts import (
    DecisionFinished,
    DecisionStarted,
    JournalEvent,
    audit_episode,
)


def test_nominal_mission_requires_verification_before_success(make_rig):
    rig = make_rig()
    rig.finish()
    assert rig.runner.summary.autonomous_success is True
    assert rig.runner.summary.decisions == 6
    events = [
        JournalEvent.model_validate_json(line) for line in rig.journal.path.read_text().splitlines()
    ]
    actions = [
        event.body.decision.selected.skill
        for event in events
        if isinstance(event.body, DecisionStarted)
    ]
    assert actions == ["NAVIGATE", "SEARCH", "PICK", "NAVIGATE", "PLACE", "VERIFY"]
    assert audit_episode(rig.journal.path).complete is True


def test_acceptance_is_not_completion(make_rig):
    rig = make_rig()
    rig.runner.tick()
    assert rig.runner.summary is None
    assert rig.executor.is_idle() is False
    report = audit_episode(rig.journal.path)
    assert "unfinished decision" in report.errors
    assert report.complete is False


def test_journal_durations_remain_auditable_when_clock_advances_between_reads(
    make_rig, monkeypatch
):
    rig = make_rig()
    original = rig.clock.monotonic
    offset = 0.0

    def sampled_monotonic():
        nonlocal offset
        offset += 0.00001
        return original() + offset

    monkeypatch.setattr(rig.clock, "monotonic", sampled_monotonic)
    rig.finish()

    report = audit_episode(rig.journal.path)
    assert report.complete is True
    assert report.errors == ()


def test_timeout_confirms_stop_before_retry(make_rig):
    rig = make_rig(faults={1: "timeout"})
    rig.finish()
    assert rig.executor.calls[:3] == [
        ("start", "decision-0001"),
        ("cancel", "decision-0001"),
        ("start", "decision-0002"),
    ]
    events = [
        JournalEvent.model_validate_json(line) for line in rig.journal.path.read_text().splitlines()
    ]
    results = [
        event.body.history_entry.verification_result.outcome
        for event in events
        if isinstance(event.body, DecisionFinished)
    ]
    assert results[0] == Outcome.TIMEOUT
    assert rig.runner.summary.autonomous_success is True


def test_unconfirmed_cancellation_never_dispatches_again(make_rig):
    rig = make_rig(faults={1: "cancel_unconfirmed"})
    rig.finish()
    assert rig.runner.summary.reason == "CANCEL_UNCONFIRMED"
    assert rig.runner.summary.autonomous_success is False
    rig.runner.tick()
    assert rig.executor.calls == [("start", "decision-0001"), ("cancel", "decision-0001")]
    assert audit_episode(rig.journal.path).complete is True


def test_unknown_result_asks_for_help_and_never_counts_as_autonomous(make_rig):
    rig = make_rig(faults={3: "unknown"})
    rig.finish()
    assert rig.runner.summary.reason == "ASK"
    assert rig.runner.summary.assistance_requested is True
    assert rig.runner.summary.autonomous_success is False
    assert rig.runner.summary.decisions == 4


def test_repeated_failure_hits_retry_limit(make_rig):
    rig = make_rig(faults={1: "failed", 2: "failed"})
    rig.finish()
    assert rig.runner.summary.reason == "RETRY_LIMIT"
    assert rig.runner.summary.decisions == 2


def test_cancel_during_action_closes_episode_after_stop(make_rig):
    rig = make_rig(faults={1: "timeout"})
    rig.runner.tick()
    rig.runner.cancel()
    rig.finish()
    assert rig.runner.summary.reason == "CANCELLED"
    assert rig.executor.is_idle() is True
    assert audit_episode(rig.journal.path).complete is True


def test_mission_deadline_cancels_active_skill(make_rig):
    rig = make_rig(
        faults={1: "timeout"},
        limits=Limits(
            mission_timeout_s=0.3,
            skill_timeout_s=1,
            cancellation_timeout_s=0.2,
        ),
    )
    rig.finish()
    assert rig.runner.summary.reason == "MISSION_TIMEOUT"
    assert rig.executor.is_idle() is True


def test_unregistered_candidate_prevents_all_dispatch(make_rig, monkeypatch):
    rig = make_rig()
    valid = Action(skill="NAVIGATE", zone="desk")
    invalid = Action(skill="NAVIGATE", zone="unregistered")
    monkeypatch.setattr(
        rig.supervisor,
        "decide",
        lambda *args: Decision(
            candidates=(
                Candidate(action=valid, generation_rank=0),
                Candidate(action=invalid, generation_rank=1),
            ),
            selected=valid,
            behavior=BehaviorMetadata(policy="test", method="scripted"),
        ),
    )
    rig.finish()
    assert rig.runner.summary.reason == "INVALID_DECISION"
    assert rig.executor.calls == []


def test_stale_observation_prevents_motion(make_rig, monkeypatch):
    rig = make_rig()
    initial = rig.executor.observe()
    monkeypatch.setattr(rig.executor, "observe", lambda: initial)
    rig.clock.advance(3)
    rig.finish()
    assert rig.runner.summary.reason == "STALE_OBSERVATION"
    assert rig.executor.calls == []


def test_slow_decision_cannot_execute_after_deadline(make_rig, monkeypatch):
    rig = make_rig(limits=Limits(mission_timeout_s=1))
    original = rig.supervisor.decide

    def slow_decision(*args):
        result = original(*args)
        rig.clock.advance(2)
        return result

    monkeypatch.setattr(rig.supervisor, "decide", slow_decision)
    rig.finish()
    assert rig.runner.summary.reason == "MISSION_TIMEOUT"
    assert rig.executor.calls == []


def test_cancel_during_decision_prevents_dispatch(make_rig, monkeypatch):
    rig = make_rig()
    original = rig.supervisor.decide

    def decision_with_cancellation(*args):
        result = original(*args)
        rig.runner.cancel()
        return result

    monkeypatch.setattr(rig.supervisor, "decide", decision_with_cancellation)
    rig.finish()
    assert rig.runner.summary.reason == "CANCELLED"
    assert rig.executor.calls == []


def test_missing_other_gripper_state_prevents_pick(make_rig, monkeypatch):
    rig = make_rig(actions=(Action(skill="PICK", object_id="book"),))
    current = rig.executor.observe()
    state = current.model_copy(
        update={
            "grippers": tuple(
                gripper.model_copy(
                    update={"state": GripperState.UNKNOWN, "object_id": None, "evidence": ()}
                )
                for gripper in current.grippers
            )
        }
    )
    monkeypatch.setattr(rig.executor, "observe", lambda: state)
    rig.finish()
    assert rig.runner.summary.reason == "RETRY_LIMIT"
    assert rig.executor.calls == []


def test_result_arriving_after_deadline_is_not_success(make_rig, monkeypatch):
    rig = make_rig(limits=Limits(mission_timeout_s=1, skill_timeout_s=1))
    original = rig.executor.poll

    def delayed_poll(identifier):
        result = original(identifier)
        rig.clock.advance(2)
        return result

    monkeypatch.setattr(rig.executor, "poll", delayed_poll)
    rig.finish()
    assert rig.runner.summary.reason == "MISSION_TIMEOUT"
    assert rig.runner.summary.autonomous_success is False


def test_artificial_observation_cannot_be_mislabeled_as_physical(make_rig, monkeypatch):
    rig = make_rig()
    wrong = rig.executor.observe().model_copy(update={"origin": Origin.PHYSICAL})
    monkeypatch.setattr(rig.executor, "observe", lambda: wrong)
    rig.finish()
    assert rig.runner.summary.autonomous_success is False
    assert rig.executor.calls == []


def test_executor_success_without_grasp_evidence_becomes_unknown(make_rig, monkeypatch):
    rig = make_rig(actions=(Action(skill="PICK", object_id="book"),))

    def complete_without_grasp(decision_id):
        rig.executor.cancel(decision_id)
        return ExecutionResult(outcome=Outcome.SUCCESS, detail="motor completed")

    monkeypatch.setattr(rig.executor, "poll", complete_without_grasp)
    rig.finish()
    assert rig.runner.summary.reason == "ASK"
    assert rig.runner.summary.autonomous_success is False


def test_disk_failure_cancels_and_permanently_faults_runner(make_rig, monkeypatch):
    rig = make_rig(faults={1: "timeout"})
    rig.runner.tick()
    original = rig.journal.append

    def broken_disk(*args):
        raise OSError("disk full")

    monkeypatch.setattr(rig.journal, "append", broken_disk)
    rig.runner.cancel()
    rig.runner.tick()
    with pytest.raises(OSError, match="disk full"):
        rig.runner.tick()
    monkeypatch.setattr(rig.journal, "append", original)
    with pytest.raises(RuntimeError, match="runner faulted"):
        rig.runner.tick()
    assert rig.executor.is_idle() is True
    assert audit_episode(rig.journal.path).complete is False


def test_manipulation_without_known_stopped_base_is_not_dispatched(make_rig, monkeypatch):
    rig = make_rig(actions=(Action(skill="PICK", object_id="book"),))
    current = rig.executor.observe()
    state = current.model_copy(
        update={"robot": current.robot.model_copy(update={"base_stopped": None})}
    )
    monkeypatch.setattr(rig.executor, "observe", lambda: state)
    rig.finish()
    assert rig.runner.summary.reason == "RETRY_LIMIT"
    assert rig.executor.calls == []


def test_precondition_rejection_is_not_logged_as_executor_failure(make_rig, monkeypatch):
    rig = make_rig(actions=(Action(skill="PICK", object_id="book"),))
    current = rig.executor.observe()
    state = current.model_copy(
        update={"robot": current.robot.model_copy(update={"base_stopped": None})}
    )
    monkeypatch.setattr(rig.executor, "observe", lambda: state)
    rig.runner.tick()
    events = [
        JournalEvent.model_validate_json(line) for line in rig.journal.path.read_text().splitlines()
    ]
    finished = next(event.body for event in events if isinstance(event.body, DecisionFinished))
    assert finished.history_entry.dispatch_status == DispatchStatus.REJECTED_PRECONDITION
    assert finished.history_entry.executor_result is None


def test_runner_waits_for_a_new_post_action_observation(make_rig, monkeypatch):
    rig = make_rig()
    rig.runner.tick()
    rig.clock.advance(0.1)
    monkeypatch.setattr(rig.executor, "observe_after", lambda *_: None)
    rig.runner.tick()
    assert rig.runner.summary is None
    events = [
        JournalEvent.model_validate_json(line) for line in rig.journal.path.read_text().splitlines()
    ]
    assert not any(isinstance(event.body, DecisionFinished) for event in events)
    rig.clock.advance(0.1)
    new_snapshot = rig.executor.observe()
    monkeypatch.setattr(
        rig.executor,
        "observe_after",
        lambda captured_at: new_snapshot if new_snapshot.captured_at > captured_at else None,
    )
    rig.runner.tick()
    events = [
        JournalEvent.model_validate_json(line) for line in rig.journal.path.read_text().splitlines()
    ]
    assert any(isinstance(event.body, DecisionFinished) for event in events)


def test_human_intervention_preserves_success_but_removes_autonomous_label(make_rig):
    rig = make_rig()
    rig.runner.record_intervention(
        Intervention(
            kind="VERBAL",
            occurred_at=rig.clock.time(),
            duration_s=1.5,
            detail="operator identified the destination",
        )
    )
    rig.finish()
    assert rig.runner.summary.mission_success is True
    assert rig.runner.summary.autonomous_success is False
    assert rig.runner.summary.intervention_count == 1
    assert audit_episode(rig.journal.path).complete is True


def test_fresh_snapshot_with_stale_manipulation_facts_is_rejected(make_rig, monkeypatch):
    rig = make_rig(actions=(Action(skill="PICK", object_id="book"),))
    stale_facts = rig.executor.observe()
    rig.clock.advance(3)
    snapshot = stale_facts.model_copy(update={"captured_at": rig.clock.time()})
    monkeypatch.setattr(rig.executor, "observe", lambda: snapshot)
    rig.finish()
    assert rig.runner.summary.reason == "RETRY_LIMIT"
    assert rig.executor.calls == []
