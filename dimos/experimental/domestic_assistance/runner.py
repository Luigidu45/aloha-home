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

"""Tick-driven mission lifecycle. Stop acknowledgement precedes subsequent action."""

from dataclasses import dataclass
from threading import Event, RLock
import time
from typing import Literal

from dimos.experimental.domestic_assistance.contracts import (
    Action,
    AttemptRecord,
    CandidateAssessment,
    DecisionContext,
    DispatchStatus,
    EpisodeSummary,
    ExecutionResult,
    HistoryEntry,
    Intervention,
    Limits,
    Mission,
    Observation,
    Outcome,
    RunMetadata,
    VerificationResult,
)
from dimos.experimental.domestic_assistance.interfaces import (
    Clock,
    Executor,
    Observer,
    Supervisor,
    Verifier,
)
from dimos.experimental.domestic_assistance.rollouts import (
    DecisionFinished,
    DecisionStarted,
    EpisodeFinished,
    EpisodeInvalidated,
    EpisodeJournal,
    EpisodeStarted,
    EventBody,
    InterventionRecorded,
)
from dimos.experimental.domestic_assistance.verification import DEFAULT_VERIFIER

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
    context: DecisionContext
    started: float
    dispatch_status: DispatchStatus = DispatchStatus.EXECUTED
    executor_result: ExecutionResult | None = None
    executor_completed_at: float | None = None
    verification_deadline: float = 0.0


class MissionRunner:
    """Run one episode through nonblocking adapters and a durable event journal.

    This class serializes calls within one instance. The physical adapter must additionally
    hold a process-wide hardware lease and enforce an independent watchdog/emergency stop.
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
        verifier: Verifier = DEFAULT_VERIFIER,
    ) -> None:
        if executor.origin != metadata.origin:
            raise ValueError("executor origin does not match episode metadata")
        if journal.episode_id != metadata.episode_id:
            raise ValueError("journal does not belong to this episode")
        if verifier.version != metadata.manifest.verifier.version:
            raise ValueError("verifier version does not match episode manifest")
        if verifier.name != metadata.manifest.verifier.name:
            raise ValueError("verifier name does not match episode manifest")
        if metadata.manifest.verifier.sha256 != verifier.fingerprint:
            raise ValueError("verifier fingerprint does not match episode manifest")
        self._mission = mission
        self._metadata = metadata
        self._executor = executor
        self._observer = observer
        self._supervisor = supervisor
        self._journal = journal
        self._limits = limits
        self._clock = clock if clock is not None else SystemClock()
        self._verifier = verifier
        self._lock = RLock()
        self._started = self._clock.monotonic()
        self._pending: PendingAction | None = None
        self._summary: EpisodeSummary | None = None
        self._history: list[HistoryEntry] = []
        self._decisions = 0
        self._last_action: Action | None = None
        self._attempts = 0
        self._stopping: ExecutionResult | None = None
        self._stop_deadline = 0.0
        self._stop_reason: Termination | None = None
        self._cancel_requested = Event()
        self._verified: set[str] = set()
        self._faulted = False
        self._interventions: list[Intervention] = []
        self._assistance_requested = False
        self._exclusion_reason: str | None = None
        self._record(EpisodeStarted(mission=mission, metadata=metadata, limits=limits))

    @property
    def summary(self) -> EpisodeSummary | None:
        return self._summary

    def cancel(self) -> None:
        """Request episode cancellation; call tick until stopped or cancellation times out."""
        self._cancel_requested.set()

    def record_intervention(self, intervention: Intervention) -> None:
        """Record assistance without silently treating the episode as autonomous."""
        with self._lock:
            if self._summary is not None:
                raise RuntimeError("cannot add an intervention to a closed episode")
            if intervention.occurred_at > self._clock.time():
                raise ValueError("intervention timestamp is in the future")
            self._interventions.append(intervention)
            self._record(InterventionRecorded(intervention=intervention))

    def mark_invalid(self, reason: str) -> None:
        """Exclude an externally invalidated run while retaining its complete record."""
        if not reason.strip():
            raise ValueError("exclusion reason must not be blank")
        with self._lock:
            if self._summary is not None:
                raise RuntimeError("cannot invalidate a closed episode")
            if self._exclusion_reason is not None:
                raise RuntimeError("episode is already invalid")
            self._exclusion_reason = reason
            self._record(EpisodeInvalidated(reason=reason))

    def _record(self, body: EventBody, elapsed_s: float | None = None) -> None:
        elapsed = self._clock.monotonic() - self._started if elapsed_s is None else elapsed_s
        self._journal.append(body, self._clock.time(), elapsed)

    def _validate_observation(self, observation: Observation) -> Observation:
        age = self._clock.time() - observation.captured_at
        if observation.origin != self._metadata.origin:
            raise ValueError("observation origin mismatch")
        if not 0 <= age <= self._limits.max_observation_age_s:
            raise ValueError("stale observation or future timestamp")
        return observation

    def _observe(self) -> Observation:
        return self._validate_observation(self._observer.observe())

    def tick(self) -> EpisodeSummary | None:
        """Advance at most one lifecycle step; all boundary calls must return promptly."""
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
                self._faulted = True
                if self._pending is not None:
                    try:
                        self._executor.cancel(self._pending.identifier)
                    except Exception:
                        pass
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
                        outcome=Outcome.CANCELLED if reason == "CANCELLED" else Outcome.TIMEOUT,
                        detail=reason,
                        failure_code="episode_cancelled"
                        if reason == "CANCELLED"
                        else "mission_timeout",
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

        context = DecisionContext(
            observation=observation,
            history=tuple(self._history),
            attempts=(
                (AttemptRecord(action=self._last_action, consecutive_attempts=self._attempts),)
                if self._last_action is not None
                else ()
            ),
        )
        try:
            decision = self._supervisor.decide(self._mission, context)
            for candidate in decision.candidates:
                self._mission.validate_action(candidate.action)
            action = decision.selected
        except (ValueError, StopIteration) as exc:
            self._finish("INVALID_DECISION", str(exc))
            return
        except Exception as exc:
            self._finish("ERROR", str(exc))
            return

        if self._cancel_requested.is_set():
            self._finish("CANCELLED")
            return
        if self._clock.monotonic() - self._started >= self._limits.mission_timeout_s:
            self._finish("MISSION_TIMEOUT")
            return
        if self._clock.time() - observation.captured_at > self._limits.max_observation_age_s:
            self._finish("STALE_OBSERVATION", "observation aged during decision generation")
            return

        assessments = tuple(
            CandidateAssessment(
                action=candidate.action,
                eligible=(
                    error := self._verifier.precondition_error(
                        self._mission,
                        candidate.action,
                        observation,
                        self._limits.max_fact_age_s,
                    )
                )
                is None,
                rejection_reason=error,
            )
            for candidate in decision.candidates
        )
        selected_assessment = next(item for item in assessments if item.action == action)
        attempts = self._attempts + 1 if action == self._last_action else 1
        if attempts > self._limits.max_consecutive_attempts:
            self._finish("RETRY_LIMIT")
            return
        self._attempts, self._last_action = attempts, action
        self._decisions += 1
        self._pending = PendingAction(
            identifier=f"decision-{self._decisions:04d}",
            action=action,
            context=context,
            started=self._clock.monotonic(),
        )
        self._record(
            DecisionStarted(
                decision_id=self._pending.identifier,
                context=context,
                decision=decision,
                candidate_assessments=assessments,
            ),
            self._pending.started - self._started,
        )

        if action.skill in {"ASK", "ABORT"}:
            self._assistance_requested = action.skill == "ASK"
            self._complete(
                VerificationResult(
                    outcome=Outcome.FAILED,
                    predicate="terminal_control_decision",
                    detail=action.reason or "",
                ),
                observation,
                None,
                DispatchStatus.TERMINAL_CONTROL,
            )
            self._finish("ASK" if action.skill == "ASK" else "ABORT", action.reason or "")
            return

        if not selected_assessment.eligible:
            self._complete(
                VerificationResult(
                    outcome=Outcome.FAILED,
                    predicate="precondition_rejected",
                    detail=selected_assessment.rejection_reason or "invalid precondition",
                ),
                observation,
                None,
                DispatchStatus.REJECTED_PRECONDITION,
            )
            return

        if action.object_id is not None and action.skill in {"PICK", "PLACE"}:
            self._verified.discard(action.object_id)
        try:
            self._executor.start(self._pending.identifier, action)
        except Exception as exc:
            self._pending.dispatch_status = DispatchStatus.DISPATCH_FAILED
            self._request_stop(
                ExecutionResult(
                    outcome=Outcome.UNKNOWN,
                    detail=f"dispatch error: {exc}",
                    failure_code="dispatch_error",
                ),
                "ERROR",
            )

    def _poll_action(self) -> None:
        pending = self._pending
        assert pending is not None
        if pending.executor_result is not None:
            self._poll_post_observation()
            return
        if self._clock.monotonic() - pending.started >= self._limits.skill_timeout_s:
            self._request_stop(
                ExecutionResult(
                    outcome=Outcome.TIMEOUT,
                    detail="skill deadline",
                    failure_code="skill_timeout",
                )
            )
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
                        outcome=Outcome.CANCELLED if reason == "CANCELLED" else Outcome.TIMEOUT,
                        detail=reason,
                        failure_code="episode_cancelled"
                        if reason == "CANCELLED"
                        else "mission_timeout",
                    ),
                    reason,
                )
                return
            if self._clock.monotonic() - pending.started >= self._limits.skill_timeout_s:
                self._request_stop(
                    ExecutionResult(
                        outcome=Outcome.TIMEOUT,
                        detail="skill deadline",
                        failure_code="skill_timeout",
                    )
                )
                return
            if not self._executor.is_idle():
                self._request_stop(
                    ExecutionResult(
                        outcome=Outcome.UNKNOWN,
                        detail="executor reported completion before stopping",
                        failure_code="completion_before_stop",
                    ),
                    "ERROR",
                )
                return
        except Exception as exc:
            self._request_stop(
                ExecutionResult(
                    outcome=Outcome.UNKNOWN,
                    detail=str(exc),
                    failure_code="executor_poll_error",
                ),
                "ERROR",
            )
            return
        pending.executor_result = result
        pending.executor_completed_at = self._clock.time()
        pending.verification_deadline = (
            self._clock.monotonic() + self._limits.verification_timeout_s
        )
        self._poll_post_observation()

    def _poll_post_observation(self) -> None:
        pending = self._pending
        assert pending is not None and pending.executor_result is not None
        try:
            assert pending.executor_completed_at is not None
            after = self._observer.observe_after(pending.executor_completed_at)
            if after is not None:
                after = self._validate_observation(after)
        except ValueError as exc:
            self._complete(
                VerificationResult(
                    outcome=Outcome.UNKNOWN,
                    predicate="post_action_observation",
                    detail=str(exc),
                ),
                None,
                pending.executor_result,
                pending.dispatch_status,
            )
            self._finish("STALE_OBSERVATION", str(exc))
            return
        except Exception as exc:
            self._complete(
                VerificationResult(
                    outcome=Outcome.UNKNOWN,
                    predicate="post_action_observation",
                    detail=str(exc),
                ),
                None,
                pending.executor_result,
                pending.dispatch_status,
            )
            self._finish("ERROR", str(exc))
            return
        if after is None:
            if self._clock.monotonic() < pending.verification_deadline:
                return
            result = pending.executor_result
            verification = VerificationResult(
                outcome=result.outcome if result.outcome != Outcome.SUCCESS else Outcome.UNKNOWN,
                predicate="post_action_observation_timeout",
                detail=(
                    result.detail
                    if result.outcome != Outcome.SUCCESS
                    else "no newer observation arrived before the verification deadline"
                ),
                evidence=result.evidence,
            )
            self._complete(verification, None, result, pending.dispatch_status)
            return

        execution_result = pending.executor_result
        verified = self._verifier.verify_action(
            self._mission,
            pending.action,
            pending.context.observation,
            after,
            execution_result,
            self._limits.max_fact_age_s,
        )
        self._retain_still_satisfied_goals(after)
        if pending.action.skill == "VERIFY" and verified.outcome == Outcome.SUCCESS:
            assert pending.action.object_id is not None
            if any(
                goal.object_id == pending.action.object_id
                and goal.destination.zone == pending.action.zone
                and goal.destination.target_id == pending.action.target_id
                and goal.destination.relation == pending.action.relation
                for goal in self._mission.goals
            ):
                self._verified.add(pending.action.object_id)
        self._complete(verified, after, execution_result, pending.dispatch_status)
        if self._verified == {goal.object_id for goal in self._mission.goals} and (
            self._verifier.mission_complete(self._mission, after, self._limits.max_fact_age_s)
        ):
            self._finish("SUCCESS")

    def _retain_still_satisfied_goals(self, state: Observation) -> None:
        satisfied: set[str] = set()
        for goal in self._mission.goals:
            obj = state.object(goal.object_id)
            if obj is None:
                continue
            destination = goal.destination
            relation = obj.relation(destination.target_id, destination.relation)
            if (
                obj.zone == destination.zone
                and relation is not None
                and relation.present
                and obj.held_by is not None
                and obj.held_by.value == "none"
                and state.captured_at - obj.observed_at <= self._limits.max_fact_age_s
                and state.captured_at - relation.observed_at <= self._limits.max_fact_age_s
            ):
                satisfied.add(goal.object_id)
        self._verified.intersection_update(satisfied)

    def _request_stop(self, result: ExecutionResult, reason: Termination | None = None) -> None:
        assert self._pending is not None
        self._stopping = result
        self._stop_reason = reason
        self._stop_deadline = self._clock.monotonic() + self._limits.cancellation_timeout_s
        try:
            self._executor.cancel(self._pending.identifier)
        except Exception as exc:
            self._stop_reason = "ERROR"
            self._stopping = ExecutionResult(
                outcome=Outcome.UNKNOWN,
                detail=f"cancel error: {exc}",
                failure_code="cancel_error",
            )

    def _poll_stop(self) -> None:
        try:
            idle = self._executor.is_idle()
        except Exception:
            idle = False
        if not idle and self._clock.monotonic() < self._stop_deadline:
            return
        assert self._stopping is not None and self._pending is not None
        stopping = self._stopping
        reason = self._stop_reason
        executor_result = (
            None if self._pending.dispatch_status == DispatchStatus.DISPATCH_FAILED else stopping
        )
        if executor_result is not None:
            self._pending.executor_completed_at = self._clock.time()
        self._complete(
            VerificationResult(
                outcome=stopping.outcome,
                predicate="stopped_after_cancellation",
                detail=stopping.detail,
                evidence=stopping.evidence,
            ),
            None,
            executor_result,
            self._pending.dispatch_status,
        )
        self._stopping = None
        if not idle:
            self._finish("CANCEL_UNCONFIRMED", "stop could not be confirmed; no further dispatch")
        elif reason is not None:
            self._finish(reason)

    def _complete(
        self,
        verification_result: VerificationResult,
        after: Observation | None,
        executor_result: ExecutionResult | None,
        dispatch_status: DispatchStatus,
    ) -> None:
        assert self._pending is not None
        completed = self._clock.monotonic()
        duration = completed - self._pending.started
        entry = HistoryEntry(
            decision_id=self._pending.identifier,
            action=self._pending.action,
            dispatch_status=dispatch_status,
            executor_result=executor_result,
            executor_completed_at=(
                self._pending.executor_completed_at if executor_result is not None else None
            ),
            verification_result=verification_result,
            duration_s=duration,
        )
        self._record(
            DecisionFinished(
                history_entry=entry,
                next_observation=after,
            ),
            completed - self._started,
        )
        self._history.append(entry)
        self._pending = None

    def _finish(self, reason: Termination, detail: str = "") -> None:
        mission_success = reason == "SUCCESS"
        assisted = self._assistance_requested or bool(self._interventions)
        completed = self._clock.monotonic()
        duration = completed - self._started
        summary = EpisodeSummary(
            reason=reason,
            mission_success=mission_success,
            autonomous_success=mission_success and not assisted,
            assistance_requested=self._assistance_requested,
            intervention_count=len(self._interventions),
            intervention_duration_s=sum(item.duration_s for item in self._interventions),
            experiment_valid=self._exclusion_reason is None,
            exclusion_reason=self._exclusion_reason,
            decisions=self._decisions,
            duration_s=duration,
            detail=detail,
        )
        self._record(EpisodeFinished(summary=summary), duration)
        self._summary = summary
