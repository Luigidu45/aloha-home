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

"""Tick-driven mission lifecycle. Stop acknowledgement precedes any subsequent action."""

from dataclasses import dataclass
from threading import Event, RLock
import time
from typing import Literal

from dimos.experimental.domestic_assistance.contracts import (
    Action,
    EpisodeSummary,
    ExecutionResult,
    Limits,
    Mission,
    Observation,
    Outcome,
    RunMetadata,
)
from dimos.experimental.domestic_assistance.interfaces import Clock, Executor, Observer, Supervisor
from dimos.experimental.domestic_assistance.rollouts import (
    DecisionFinished,
    DecisionStarted,
    EpisodeFinished,
    EpisodeJournal,
    EpisodeStarted,
    EventBody,
)
from dimos.experimental.domestic_assistance.verification import (
    mission_complete,
    precondition_error,
    verify_action,
)

Termination = Literal[
    "SUCCESS",
    "ABORT",
    "ASK",
    "CANCELLED",
    "MISSION_TIMEOUT",
    "DECISION_LIMIT",
    "RETRY_LIMIT",
    "INVALID_DECISION",
    "STALE_OBSERVATION",
    "ERROR",
    "CANCEL_UNCONFIRMED",
]


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def time(self) -> float:
        return time.time()


@dataclass
class PendingAction:
    identifier: str
    action: Action
    observation: Observation
    started: float


class MissionRunner:
    """One episode and one executor per instance. Calls are serialized, not threaded.

    Adapters must bound their calls; this class cannot interrupt a blocking driver.
    If cancellation is unconfirmed, the instance terminates and may never dispatch again.
    """

    def __init__(
        self,
        mission: Mission,
        metadata: RunMetadata,
        executor: Executor,
        observer: Observer,
        supervisor: Supervisor,
        journal: EpisodeJournal,
        limits: Limits = Limits(),
        clock: Clock | None = None,
    ) -> None:
        if executor.origin != metadata.origin:
            raise ValueError("executor origin does not match episode metadata")
        if journal.episode_id != metadata.episode_id:
            raise ValueError("journal does not belong to this episode")
        self._mission = mission
        self._metadata = metadata
        self._executor = executor
        self._observer = observer
        self._supervisor = supervisor
        self._journal = journal
        self._limits = limits
        self._clock = clock if clock is not None else SystemClock()
        self._lock = RLock()
        self._started = self._clock.monotonic()
        self._pending: PendingAction | None = None
        self._summary: EpisodeSummary | None = None
        self._history: list[ExecutionResult] = []
        self._decisions = 0
        self._last_action: Action | None = None
        self._attempts = 0
        self._stopping: ExecutionResult | None = None
        self._stop_deadline = 0.0
        self._stop_reason: Termination | None = None
        self._cancel_requested = Event()
        self._verified: set[str] = set()
        self._faulted = False
        self._record(EpisodeStarted(mission=mission, metadata=metadata, limits=limits))

    @property
    def summary(self) -> EpisodeSummary | None:
        return self._summary

    def cancel(self) -> None:
        """Request episode cancellation; call tick until stopped or cancellation times out."""
        self._cancel_requested.set()

    def _record(self, body: EventBody) -> None:
        self._journal.append(body, self._clock.time(), self._clock.monotonic() - self._started)

    def _observe(self) -> Observation:
        observation = self._observer.observe()
        age = self._clock.time() - observation.captured_at
        if observation.origin != self._metadata.origin:
            raise ValueError("observation origin mismatch")
        if not 0 <= age <= self._limits.max_observation_age_s:
            raise ValueError("stale observation or future timestamp")
        return observation

    def tick(self) -> EpisodeSummary | None:
        """Advance at most one lifecycle step. No sleeps or executor work in background threads."""
        with self._lock:
            if self._faulted:
                raise RuntimeError(
                    "runner faulted; reconcile executor and journal before a new episode"
                )
            if self._summary is not None:
                return self._summary
            try:
                self._tick()
            except BaseException:
                # A journal/disk error must not leave motion running silently.
                self._faulted = True
                if self._pending is not None:
                    try:
                        self._executor.cancel(self._pending.identifier)
                    except Exception:
                        pass  # Preserve the original failure; the runner is permanently faulted.
                raise
            return self._summary

    def _tick(self) -> None:
        if self._stopping is not None:
            self._poll_stop()
            return
        expired = self._clock.monotonic() - self._started >= self._limits.mission_timeout_s
        if self._cancel_requested.is_set() or expired:
            reason: Termination = (
                "CANCELLED" if self._cancel_requested.is_set() else "MISSION_TIMEOUT"
            )
            if self._pending is None:
                self._finish(reason)
            else:
                self._request_stop(
                    ExecutionResult(
                        outcome=Outcome.UNKNOWN if reason == "CANCELLED" else Outcome.TIMEOUT,
                        detail=reason,
                    ),
                    reason,
                )
            return
        if self._pending is not None:
            self._poll_action()
            return
        if self._decisions >= self._limits.max_decisions:
            self._finish("DECISION_LIMIT")
            return
        if not self._executor.is_idle():
            self._finish("CANCEL_UNCONFIRMED", "executor was not idle before dispatch")
            return
        try:
            observation = self._observe()
        except ValueError as exc:
            self._finish("STALE_OBSERVATION", str(exc))
            return
        except Exception as exc:
            self._finish("ERROR", str(exc))
            return
        try:
            decision = self._supervisor.decide(self._mission, observation, tuple(self._history))
            for candidate in decision.candidates:
                self._mission.validate_action(candidate)
            action = decision.selected
        except (ValueError, StopIteration) as exc:
            self._finish("INVALID_DECISION", str(exc))
            return
        except Exception as exc:
            self._finish("ERROR", str(exc))
            return
        # Inference may consume the remaining budget or make its input stale.
        if self._cancel_requested.is_set():
            self._finish("CANCELLED")
            return
        if self._clock.monotonic() - self._started >= self._limits.mission_timeout_s:
            self._finish("MISSION_TIMEOUT")
            return
        if self._clock.time() - observation.captured_at > self._limits.max_observation_age_s:
            self._finish("STALE_OBSERVATION", "observation aged during decision generation")
            return
        attempts = self._attempts + 1 if action == self._last_action else 1
        if attempts > self._limits.max_consecutive_attempts:
            self._finish("RETRY_LIMIT")
            return
        self._attempts, self._last_action = attempts, action
        self._decisions += 1
        self._pending = PendingAction(
            identifier=f"decision-{self._decisions:04d}",
            action=action,
            observation=observation,
            started=self._clock.monotonic(),
        )
        self._record(
            DecisionStarted(
                decision_id=self._pending.identifier,
                observation=observation,
                decision=decision,
            )
        )
        if action.skill in {"ASK", "ABORT"}:
            self._complete(
                ExecutionResult(outcome=Outcome.FAILED, detail=action.reason or ""), observation
            )
            self._finish("ASK" if action.skill == "ASK" else "ABORT", action.reason or "")
            return
        error = precondition_error(action, observation)
        target = observation.object(action.object_id)
        if (
            action.skill in {"PICK", "PLACE"}
            and target is not None
            and (self._clock.time() - target.observed_at > self._limits.max_observation_age_s)
        ):
            error = "target observation is stale"
        if error is not None:
            self._complete(ExecutionResult(outcome=Outcome.FAILED, detail=error), observation)
            return
        if action.object_id is not None and action.skill in {"PICK", "PLACE"}:
            self._verified.discard(action.object_id)
        try:
            self._executor.start(self._pending.identifier, action)
        except Exception as exc:
            self._request_stop(
                ExecutionResult(outcome=Outcome.UNKNOWN, detail=f"dispatch error: {exc}"),
                "ERROR",
            )

    def _poll_action(self) -> None:
        pending = self._pending
        assert pending is not None
        if self._clock.monotonic() - pending.started >= self._limits.skill_timeout_s:
            self._request_stop(ExecutionResult(outcome=Outcome.TIMEOUT, detail="skill deadline"))
            return
        try:
            result = self._executor.poll(pending.identifier)
            if result is None:
                return
            if self._cancel_requested.is_set() or (
                self._clock.monotonic() - self._started >= self._limits.mission_timeout_s
            ):
                reason: Termination = (
                    "CANCELLED" if self._cancel_requested.is_set() else "MISSION_TIMEOUT"
                )
                self._request_stop(
                    ExecutionResult(
                        outcome=Outcome.UNKNOWN if reason == "CANCELLED" else Outcome.TIMEOUT,
                        detail=reason,
                    ),
                    reason,
                )
                return
            if self._clock.monotonic() - pending.started >= self._limits.skill_timeout_s:
                self._request_stop(
                    ExecutionResult(outcome=Outcome.TIMEOUT, detail="skill deadline")
                )
                return
            if not self._executor.is_idle():
                self._request_stop(
                    ExecutionResult(
                        outcome=Outcome.UNKNOWN,
                        detail="executor reported completion before stopping",
                    ),
                    "ERROR",
                )
                return
        except Exception as exc:
            self._request_stop(ExecutionResult(outcome=Outcome.UNKNOWN, detail=str(exc)), "ERROR")
            return
        try:
            after = self._observe()
            if after.captured_at < pending.observation.captured_at:
                raise ValueError("next observation predates action")
        except ValueError as exc:
            self._complete(ExecutionResult(outcome=Outcome.UNKNOWN, detail=str(exc)), None)
            self._finish("STALE_OBSERVATION", str(exc))
            return
        except Exception as exc:
            self._complete(ExecutionResult(outcome=Outcome.UNKNOWN, detail=str(exc)), None)
            self._finish("ERROR", str(exc))
            return
        verified = verify_action(pending.action, pending.observation, after, result)
        self._verified.intersection_update(
            goal.object_id
            for goal in self._mission.goals
            if (obj := after.object(goal.object_id)) is not None
            and obj.zone == goal.destination
            and obj.held is False
        )
        if pending.action.skill == "VERIFY" and verified.outcome == Outcome.SUCCESS:
            assert pending.action.object_id is not None
            if any(
                goal.object_id == pending.action.object_id
                and goal.destination == pending.action.zone
                for goal in self._mission.goals
            ):
                self._verified.add(pending.action.object_id)
        self._complete(verified, after, result)
        if self._verified == {goal.object_id for goal in self._mission.goals} and mission_complete(
            self._mission,
            after,
        ):
            self._finish("SUCCESS")

    def _request_stop(self, result: ExecutionResult, reason: Termination | None = None) -> None:
        assert self._pending is not None
        self._stopping = result
        self._stop_reason = reason
        self._stop_deadline = self._clock.monotonic() + self._limits.cancellation_timeout_s
        try:
            self._executor.cancel(self._pending.identifier)
        except Exception as exc:
            self._stop_reason = "ERROR"
            self._stopping = ExecutionResult(outcome=Outcome.UNKNOWN, detail=f"cancel error: {exc}")

    def _poll_stop(self) -> None:
        try:
            idle = self._executor.is_idle()
        except Exception:
            idle = False
        if not idle and self._clock.monotonic() < self._stop_deadline:
            return
        assert self._stopping is not None
        reason = self._stop_reason
        self._complete(self._stopping, None)
        self._stopping = None
        if not idle:
            self._finish("CANCEL_UNCONFIRMED", "stop could not be confirmed; no further dispatch")
        elif reason is not None:
            self._finish(reason)

    def _complete(
        self,
        result: ExecutionResult,
        after: Observation | None,
        execution_result: ExecutionResult | None = None,
    ) -> None:
        assert self._pending is not None
        self._record(
            DecisionFinished(
                decision_id=self._pending.identifier,
                result=result,
                execution_result=execution_result,
                next_observation=after,
                duration_s=self._clock.monotonic() - self._pending.started,
            )
        )
        self._history.append(result)
        self._pending = None

    def _finish(self, reason: Termination, detail: str = "") -> None:
        summary = EpisodeSummary(
            reason=reason,
            autonomous_success=reason == "SUCCESS",
            assistance_requested=reason == "ASK",
            decisions=self._decisions,
            duration_s=self._clock.monotonic() - self._started,
            detail=detail,
        )
        self._record(EpisodeFinished(summary=summary))
        self._summary = summary
