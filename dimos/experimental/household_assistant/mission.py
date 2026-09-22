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

"""Single, nonblocking F4 dispatcher. Executors consume commands outside its lock.

Only admitted actions enter the outbox. Motor completion and observed success are
separate transitions. Missing stop evidence latches admission closed indefinitely.
"""

from collections import deque
from collections.abc import Sequence
import math
import threading

from dimos.experimental.household_assistant.assessment import assess_requirements
from dimos.experimental.household_assistant.configuration import PilotConfiguration
from dimos.experimental.household_assistant.contracts import (
    ActionProposal,
    ExecutionReport,
    ExecutionStage,
    FactKey,
    MissionRequest,
    Operation,
    Origin,
    Predicate,
    Verdict,
    Verification,
)
from dimos.experimental.household_assistant.mission_contracts import (
    Arm,
    ExecutorBinding,
    ExecutorCommand,
    ExecutorResult,
    MissionEvent,
    MissionPlanningState,
    MissionSnapshot,
    MissionState,
    WorldFrame,
)
from dimos.experimental.household_assistant.mission_verification import (
    carrying,
    empty,
    fact,
    postconditions,
    preconditions,
    stopped,
)


class MissionManager:
    """Thread-safe state machine with explicit time; no network, models or motors.

    F4 intentionally rejects physical bindings: calibration, real perception and
    motor adapters belong to F8/F9. Artificial outputs cannot enter that catalog.
    The trusted adapter supplies sensor frames and consumes the outbox once.
    """

    def __init__(
        self,
        pilot: PilotConfiguration,
        bindings: Sequence[ExecutorBinding],
        *,
        arm: Arm = "right",
        clock_id: str = "unix",
        max_age_s: float = 2.0,
        stop_timeout_s: float = 5.0,
        verification_timeout_s: float = 3.0,
    ) -> None:
        if any(
            not math.isfinite(x) or x <= 0
            for x in (max_age_s, stop_timeout_s, verification_timeout_s)
        ):
            raise ValueError("timeouts and freshness limits must be finite and positive")
        if len({b.id for b in bindings}) != len(bindings) or not bindings:
            raise ValueError("executor bindings must be nonempty and unique")
        if any(
            b.origin not in {Origin.TEST, Origin.SIMULATION}
            or b.artificial != (b.origin == Origin.TEST)
            for b in bindings
        ):
            raise ValueError("F4 accepts only explicitly artificial or simulated executors")
        if pilot.transport.arm is not None and pilot.transport.arm != arm:
            raise ValueError("arm differs from pilot transport configuration")
        self.pilot = pilot
        self.arm = arm
        self.clock_id = clock_id
        self.max_age_s = max_age_s
        self.stop_timeout_s = stop_timeout_s
        self.verification_timeout_s = verification_timeout_s
        self._bindings = {b.id: b for b in bindings}
        self._lock = threading.RLock()
        self._frame: WorldFrame | None = None
        self._request: MissionRequest | None = None
        self._requests: dict[str, MissionRequest] = {}
        self._snapshots: dict[str, MissionSnapshot] = {}
        self._actions: dict[str, ActionProposal] = {}
        self._snapshot = MissionSnapshot(arm=arm)
        self._commands: deque[ExecutorCommand] = deque()
        self._events: list[MissionEvent] = []
        self._started_at = 0.0
        self._finished_at: float | None = None
        self._stopped_ack: float | None = None
        self._last_result_at = -1.0
        self._stop_outcome: MissionState = "cancelled"
        self._payload_uncertain = False
        self._last_now = 0.0

    def _time(self, now: float) -> None:
        if not math.isfinite(now) or now < self._last_now:
            raise ValueError("manager time must be finite and monotonic")
        self._last_now = now

    def _emit(
        self,
        kind: str,
        detail: str,
        now: float,
        *,
        verification: Verification | None = None,
        command: ExecutorCommand | None = None,
    ) -> None:
        self._events.append(
            MissionEvent(
                sequence=len(self._events),
                request_id=self._snapshot.request_id,
                action_id=self._snapshot.action.id if self._snapshot.action else None,
                at=now,
                clock_id=self.clock_id,
                kind=kind,
                detail=detail,
                state=self._snapshot.state,
                verification=verification,
                command=command,
            )
        )
        if self._snapshot.request_id:
            self._snapshots[self._snapshot.request_id] = self._snapshot

    def snapshot(self) -> MissionSnapshot:
        with self._lock:
            return self._snapshot

    def events(self, after_sequence: int = -1) -> tuple[MissionEvent, ...]:
        with self._lock:
            return tuple(e for e in self._events if e.sequence > after_sequence)

    def take_commands(self) -> tuple[ExecutorCommand, ...]:
        """One adapter owns this queue; do not fan out commands to competing executors."""
        with self._lock:
            commands = tuple(self._commands)
            self._commands.clear()
            return commands

    def _check(
        self, keys: tuple[FactKey, ...], now: float, *, after: float | None = None
    ) -> Verification:
        frame = self._frame
        if (
            frame is None
            or not frame.connected
            or frame.clock_id != self.clock_id
            or not 0 <= now - frame.captured_at <= self.max_age_s
        ):
            return Verification(
                verdict=Verdict.UNKNOWN, reason="missing_stale_or_disconnected_world"
            )
        return assess_requirements(
            keys,
            frame.observations,
            now=now,
            clock_id=self.clock_id,
            max_age_s=self.max_age_s,
            allowed_origins=frozenset({Origin.TEST, Origin.SIMULATION}),
            after=after,
        )

    def _cameras_current(
        self, camera_ids: tuple[str, ...], now: float, after: float | None = None
    ) -> bool:
        if self._frame is None:
            return False
        for alias in camera_ids:
            evidence = self._frame.cameras.get(alias)
            if (
                evidence is None
                or evidence.clock_id != self.clock_id
                or evidence.origin not in {Origin.TEST, Origin.SIMULATION}
                or not 0 <= now - evidence.captured_at <= self.max_age_s
            ):
                return False
            if after is not None and evidence.captured_at <= after:
                return False
        return True

    def submit(self, request: MissionRequest, *, now: float) -> MissionSnapshot:
        with self._lock:
            self._time(now)
            self.pilot.validate_request(request)
            if request.id in self._requests:
                if self._requests[request.id] != request:
                    raise ValueError("request id reused with a different payload")
                return (
                    self._snapshot
                    if self._snapshot.request_id == request.id
                    else self._snapshots[request.id]
                )
            if self._snapshot.state not in {"idle", "cancelled", "failed", "succeeded"}:
                raise RuntimeError("another mission is active or its stop is unconfirmed")
            ready = self._check(stopped() + empty(), now)
            if ready.verdict != Verdict.SUCCESS:
                raise RuntimeError("new mission requires observed stop and empty grippers")
            self._request = request
            self._requests[request.id] = request
            self._payload_uncertain = False
            self._snapshot = MissionSnapshot(
                request_id=request.id,
                state="preparing",
                reason="request_accepted",
                arm=self.arm,
                revision=self._frame.revision if self._frame else -1,
            )
            self._emit("request", request.model_dump_json(), now)
            return self._snapshot

    def select_target(
        self, object_id: str, *, expected_revision: int, now: float, by_user: bool = True
    ) -> MissionSnapshot:
        with self._lock:
            self._time(now)
            request = self._request
            if (
                request is None
                or self._snapshot.action is not None
                or self._snapshot.state not in {"preparing", "searching", "asking"}
            ):
                raise RuntimeError("target selection is not currently allowed")
            if expected_revision != self._snapshot.revision:
                raise ValueError("scene changed since target proposal")
            self.pilot.validate_request(
                request.model_copy(update={"selected_object_id": object_id})
            )
            if request.selected_object_id is not None and request.selected_object_id != object_id:
                raise ValueError("target differs from explicit request")
            verified = self._check(
                (
                    fact(object_id, Predicate.VISIBLE),
                    fact(object_id, Predicate.AT, request.source_id),
                ),
                now,
            )
            if verified.verdict != Verdict.SUCCESS:
                raise ValueError("target requires current, source-bound evidence")
            self._snapshot = self._snapshot.model_copy(
                update={
                    "selected_object_id": object_id,
                    "state": "preparing",
                    "reason": "target_confirmed",
                }
            )
            self._emit(
                "clarification_answer" if by_user else "target_selection",
                object_id,
                now,
                verification=verified,
            )
            return self._snapshot

    def ask(self, reason: str, *, now: float) -> None:
        with self._lock:
            self._time(now)
            if (
                self._snapshot.state not in {"preparing", "searching"}
                or self._snapshot.action is not None
            ):
                raise RuntimeError("questions require an idle action slot")
            self._snapshot = self._snapshot.model_copy(update={"state": "asking", "reason": reason})
            self._emit("clarification_requested", reason, now)

    def propose(
        self, action: ActionProposal, *, expected_revision: int, now: float
    ) -> MissionSnapshot:
        with self._lock:
            self._time(now)
            if action.id in self._actions:
                if self._actions[action.id] != action:
                    raise ValueError("action id reused with a different payload")
                return self._snapshots[action.request_id]
            if (
                self._request is None
                or self._snapshot.state not in {"preparing", "searching"}
                or self._snapshot.action is not None
            ):
                raise RuntimeError("mission is not accepting actions")
            if expected_revision != self._snapshot.revision:
                raise ValueError("scene changed since action proposal")
            skill = self.pilot.validate_action(
                self._request, action, available_executor_ids=self._bindings
            )
            binding = self._bindings[skill.executor_id]
            if skill.operation not in binding.operations:
                raise ValueError("executor does not implement this operation")
            if action.arm is not None and action.arm != self.arm:
                raise ValueError("action arm differs from mission arm")
            if (
                skill.operation == Operation.PICK
                and action.object_id != self._snapshot.selected_object_id
            ):
                raise ValueError("pickup requires confirmed target selection")
            if (
                skill.operation in {Operation.STOW, Operation.PLACE}
                and action.object_id != self._snapshot.held_object_id
            ):
                raise ValueError("operation requires the currently verified payload")
            if self._payload_uncertain:
                raise RuntimeError("payload uncertain; reconcile before another action")
            verified = self._check(
                preconditions(
                    skill.operation, action, self._request, self._snapshot.held_object_id, self.arm
                ),
                now,
            )
            if verified.verdict != Verdict.SUCCESS or not self._cameras_current(
                skill.required_cameras, now
            ):
                self._emit(
                    "admission_rejected",
                    "preconditions_or_cameras_unconfirmed",
                    now,
                    verification=verified,
                )
                raise ValueError("current preconditions and required cameras must be confirmed")
            self._actions[action.id] = action
            self._started_at = now
            self._finished_at = None
            self._stopped_ack = None
            self._last_result_at = -1
            state: MissionState = (
                "navigating"
                if skill.operation == Operation.NAVIGATE
                else "searching"
                if skill.operation == Operation.OBSERVE
                else "manipulating"
            )
            self._snapshot = self._snapshot.model_copy(
                update={
                    "state": state,
                    "action": action,
                    "reason": "action_dispatched",
                    "verification": None,
                    "stop_requested_at": None,
                    "stop_confirmed_at": None,
                }
            )
            command = ExecutorCommand(
                kind="start",
                executor_id=binding.id,
                action=action,
                issued_at=now,
                clock_id=self.clock_id,
            )
            self._commands.append(command)
            self._emit(
                "dispatch",
                f"{binding.id}:{binding.origin}:artificial={binding.artificial}",
                now,
                verification=verified,
                command=command,
            )
            return self._snapshot

    def planning_state(self) -> MissionPlanningState:
        with self._lock:
            return MissionPlanningState(
                request=self._request, state=self._snapshot, world=self._frame
            ).model_copy(deep=True)

    def admit_planner(
        self,
        *,
        expected: MissionSnapshot,
        request: MissionRequest | None,
        action: ActionProposal | None,
        question: str | None,
        target: str | None,
        now: float,
    ) -> MissionSnapshot:
        """Atomically reject decisions overtaken by cancellation, progress or scene changes."""
        with self._lock:
            self._time(now)
            if self._snapshot != expected:
                raise ValueError("mission changed during inference")
            if self._check(stopped(), now).verdict != Verdict.SUCCESS:
                raise ValueError("planner admission requires current observed stop")
            if sum(x is not None for x in (request, action, question)) != 1:
                raise ValueError("exactly one planner outcome required")
            if request is not None:
                return self.submit(request, now=now)
            if question is not None:
                if self._snapshot.state == "idle":
                    self._emit("clarification_requested", question, now)
                else:
                    self.ask(question, now=now)
                return self._snapshot
            if target is not None:
                self.select_target(
                    target, expected_revision=expected.revision, now=now, by_user=False
                )
            assert action is not None
            return self.propose(action, expected_revision=expected.revision, now=now)

    def update_world(self, frame: WorldFrame, *, now: float) -> None:
        with self._lock:
            self._time(now)
            if frame.clock_id != self.clock_id or frame.captured_at > now:
                raise ValueError("incompatible world clock or future frame")
            if self._frame and (
                frame.captured_at <= self._frame.captured_at
                or frame.revision < self._frame.revision
            ):
                raise ValueError("world frames must advance without rolling back revision")
            self._frame = frame.model_copy(deep=True)
            self._snapshot = self._snapshot.model_copy(update={"revision": frame.revision})
            self._advance(now)

    def receive(self, result: ExecutorResult, *, now: float) -> None:
        with self._lock:
            self._time(now)
            action = self._snapshot.action
            if (
                action is None
                or result.action_id != action.id
                or result.executor_id != self.pilot.skill(action.skill_id).executor_id
            ):
                self._emit("result_ignored", "unmatched_action_or_executor", now)
                return
            if (
                result.clock_id != self.clock_id
                or not self._started_at <= result.recorded_at <= now
                or result.recorded_at < self._last_result_at
            ):
                self._emit("result_ignored", "incompatible_or_out_of_order_result", now)
                return
            self._last_result_at = result.recorded_at
            if self._snapshot.state in {"stopping", "stop_unconfirmed"}:
                requested = self._snapshot.stop_requested_at
                if (
                    result.stage == "stopped"
                    and requested is not None
                    and result.recorded_at >= requested
                ):
                    self._stopped_ack = result.recorded_at
                else:
                    self._emit("result_ignored", "completion_cannot_override_cancellation", now)
                self._advance(now)
                return
            if self._finished_at is not None:
                self._emit("result_ignored", "duplicate_terminal_result", now)
                return
            if result.stage == "finished":
                self._finished_at = result.recorded_at
                self._snapshot = self._snapshot.model_copy(
                    update={"state": "verifying", "reason": "executor_finished_not_yet_verified"}
                )
            elif result.stage in {"failed", "stopped"}:
                self._begin_stop("failed", result.detail, now)
            self._emit("executor_result", result.model_dump_json(), now)
            self._advance(now)

    def cancel(self, *, now: float, pause: bool = False) -> MissionSnapshot:
        with self._lock:
            self._time(now)
            if self._snapshot.state in {"idle", "succeeded", "failed", "cancelled"}:
                return self._snapshot
            if self._snapshot.state not in {"stopping", "stop_unconfirmed"}:
                self._begin_stop(
                    "paused" if pause else "cancelled",
                    "user_pause" if pause else "user_cancel",
                    now,
                )
            self._advance(now)
            return self._snapshot

    def fail(self, reason: str, *, now: float) -> None:
        """Fail closed on adapter/control errors, keeping the observed-stop gate."""
        with self._lock:
            self._time(now)
            if self._snapshot.state not in {
                "idle",
                "succeeded",
                "failed",
                "cancelled",
                "stopping",
                "stop_unconfirmed",
            }:
                self._begin_stop("failed", reason, now)
            self._emit("runtime_error", reason, now)

    def _begin_stop(self, outcome: MissionState, reason: str, now: float) -> None:
        self._stop_outcome = outcome
        self._stopped_ack = None
        action = self._snapshot.action
        if action and self.pilot.skill(action.skill_id).operation in {
            Operation.PICK,
            Operation.PLACE,
        }:
            self._payload_uncertain = True
        self._snapshot = self._snapshot.model_copy(
            update={"state": "stopping", "reason": reason, "stop_requested_at": now}
        )
        # A not-yet-delivered start must never run after cancellation.
        self._commands.clear()
        if action:
            command = ExecutorCommand(
                kind="stop",
                executor_id=self.pilot.skill(action.skill_id).executor_id,
                action=action,
                issued_at=now,
                clock_id=self.clock_id,
            )
            self._commands.append(command)
            self._emit("stop_requested", reason, now, command=command)
        else:
            self._stopped_ack = now
            self._emit("stop_requested", reason, now)

    def resume(self, *, now: float) -> MissionSnapshot:
        """Reconcile observed payload; never continue an interrupted action/chunk."""
        with self._lock:
            self._time(now)
            if self._snapshot.state != "paused":
                raise RuntimeError("only a confirmed paused mission can be prepared again")
            if self._check(stopped(), now).verdict != Verdict.SUCCESS:
                raise RuntimeError("cannot resume without confirmed stopped actuators")
            selected = self._snapshot.selected_object_id
            held: str | None = None
            if self._check(empty(), now).verdict != Verdict.SUCCESS:
                if (
                    selected is None
                    or self._check(
                        (
                            fact(selected, Predicate.HELD, arm=self.arm),
                            fact(
                                "gripper",
                                Predicate.EMPTY,
                                arm="left" if self.arm == "right" else "right",
                            ),
                        ),
                        now,
                    ).verdict
                    != Verdict.SUCCESS
                ):
                    raise RuntimeError("payload reconciliation is inconclusive")
                held = selected
            self._payload_uncertain = False
            self._snapshot = self._snapshot.model_copy(
                update={
                    "state": "preparing",
                    "reason": "reprepared_after_pause",
                    "action": None,
                    "held_object_id": held,
                    "selected_object_id": selected if held else None,
                    "completed_actions": (),
                    "verification": None,
                }
            )
            self._emit("intervention", "resume_reprepared_not_replayed", now)
            return self._snapshot

    def clarify(self, answer: str, *, expected_revision: int, now: float) -> MissionSnapshot:
        """Keep conversational context; a user's text never creates sensor evidence."""
        with self._lock:
            if self._request is None or self._snapshot.state != "asking":
                raise RuntimeError("no clarification pending")
            if expected_revision != self._snapshot.revision:
                raise ValueError("scene changed before clarification")
            if self._check(stopped(), now).verdict != Verdict.SUCCESS:
                raise ValueError("clarification requires observed stop")
            if not answer.strip() or len(answer) > 500:
                raise ValueError("clarification must contain 1 to 500 characters")
            instruction = self._request.instruction + "\nAclaración del usuario: " + answer.strip()
            if len(instruction) > 1000:
                raise ValueError("conversation limit reached; pause and review the task")
            self._request = self._request.model_copy(update={"instruction": instruction})
            self._requests[self._request.id] = self._request
            self._snapshot = self._snapshot.model_copy(
                update={"state": "preparing", "reason": "clarification_received"}
            )
            self._emit("clarification_text", answer, now)
            return self._snapshot

    def redirect(
        self, destination_id: str, *, expected_revision: int, now: float
    ) -> MissionSnapshot:
        """Confirm a new destination only after observed pause; reconcile payload before moving."""
        with self._lock:
            if self._request is None or self._snapshot.state != "paused":
                raise RuntimeError("destination change requires a confirmed pause")
            if self._snapshot.revision != expected_revision:
                raise ValueError("scene changed before destination confirmation")
            revised = self._request.model_copy(update={"destination_id": destination_id})
            self.pilot.validate_request(revised)
            # Reconciliation must succeed before changing the accepted request.
            self.resume(now=now)
            self._request = revised
            self._requests[revised.id] = revised
            self._emit("destination_changed", destination_id, now)
            return self._snapshot

    def tick(self, *, now: float) -> None:
        with self._lock:
            self._time(now)
            self._advance(now)

    def _advance(self, now: float) -> None:
        snapshot = self._snapshot
        if snapshot.state in {"stopping", "stop_unconfirmed"}:
            assert snapshot.stop_requested_at is not None
            verification = self._check(stopped(), now, after=snapshot.stop_requested_at)
            if self._stopped_ack is not None and verification.verdict == Verdict.SUCCESS:
                self._snapshot = snapshot.model_copy(
                    update={
                        "state": self._stop_outcome,
                        "action": None,
                        "stop_confirmed_at": now,
                        "stop_verification": verification,
                    }
                )
                self._emit("stop_confirmed", snapshot.reason, now, verification=verification)
            elif (
                now - snapshot.stop_requested_at >= self.stop_timeout_s
                and snapshot.state != "stop_unconfirmed"
            ):
                self._snapshot = snapshot.model_copy(update={"state": "stop_unconfirmed"})
                self._emit(
                    "stop_unconfirmed", "admission_remains_locked", now, verification=verification
                )
            return
        action = snapshot.action
        if action is None:
            return
        skill = self.pilot.skill(action.skill_id)
        frame = self._frame
        if (
            frame is None
            or not frame.connected
            or not 0 <= now - frame.captured_at <= self.max_age_s
        ):
            self._begin_stop("failed", "sensor_disconnect_or_stale_world", now)
            return
        if not self._cameras_current(skill.required_cameras, now):
            self._begin_stop("failed", "required_camera_stale", now)
            return
        if skill.operation in {Operation.NAVIGATE, Operation.ALIGN} and snapshot.held_object_id:
            guard = self._check(carrying(snapshot.held_object_id, self.arm), now)
            if guard.verdict != Verdict.SUCCESS:
                self._begin_stop("failed", "transport_retention_or_posture_unconfirmed", now)
                return
        if self._finished_at is None:
            if now - self._started_at >= skill.timeout_s:
                self._begin_stop("failed", "action_timeout", now)
            return
        verification = self._check(
            postconditions(skill.operation, action, snapshot.held_object_id, self.arm),
            now,
            after=self._finished_at,
        )
        if skill.operation == Operation.OBSERVE and not self._cameras_current(
            skill.required_cameras, now, after=self._finished_at
        ):
            verification = Verification(
                verdict=Verdict.UNKNOWN, reason="no_post_action_camera_frame"
            )
        self._snapshot = snapshot.model_copy(update={"verification": verification})
        if verification.verdict == Verdict.SUCCESS:
            held = snapshot.held_object_id
            if skill.operation == Operation.PICK:
                held = action.object_id
            elif skill.operation == Operation.PLACE:
                held = None
            self._snapshot = self._snapshot.model_copy(
                update={
                    "state": "succeeded" if skill.operation == Operation.PLACE else "preparing",
                    "reason": "mission_verified"
                    if skill.operation == Operation.PLACE
                    else "action_verified",
                    "held_object_id": held,
                    "completed_actions": (*snapshot.completed_actions, action.skill_id),
                    "action": None,
                }
            )
            self._emit("verification", action.id, now, verification=verification)
        elif (
            verification.verdict == Verdict.FAILURE
            or now - self._finished_at >= self.verification_timeout_s
        ):
            self._begin_stop(
                "failed",
                "postconditions_false"
                if verification.verdict == Verdict.FAILURE
                else "postconditions_inconclusive",
                now,
            )
            self._emit("verification", action.id, now, verification=verification)

    def completed_execution(self) -> ExecutionReport | None:
        """Verified placement report for the F3 memory adapter, not an alternative verdict."""
        with self._lock:
            if (
                self._snapshot.state != "succeeded"
                or self._finished_at is None
                or not self._request
            ):
                return None
            actions = [
                a
                for a in self._actions.values()
                if a.request_id == self._request.id
                and self.pilot.skill(a.skill_id).operation == Operation.PLACE
            ]
            if not actions:
                return None
            return ExecutionReport(
                action_id=actions[-1].id,
                stage=ExecutionStage.FINISHED,
                recorded_at=self._finished_at,
                clock_id=self.clock_id,
                detail="placement_executor_finished_separately_verified",
            )
