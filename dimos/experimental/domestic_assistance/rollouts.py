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

"""Append-only episode journal with auditable decisions, evidence and interventions."""

import hashlib
import os
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, ValidationError

from dimos.experimental.domestic_assistance.contracts import (
    CandidateAssessment,
    Contract,
    Decision,
    DecisionContext,
    EpisodeSummary,
    EvidenceRef,
    HistoryEntry,
    Identifier,
    Intervention,
    Limits,
    Mission,
    Observation,
    Origin,
    Outcome,
    RunMetadata,
    Seconds,
)
from dimos.experimental.domestic_assistance.interfaces import Verifier
from dimos.experimental.domestic_assistance.verification import (
    DEFAULT_VERIFIER_REGISTRY,
    VerifierRegistry,
)


class EpisodeStarted(Contract):
    kind: Literal["episode_started"] = "episode_started"
    mission: Mission
    metadata: RunMetadata
    limits: Limits


class DecisionStarted(Contract):
    kind: Literal["decision_started"] = "decision_started"
    decision_id: Identifier
    context: DecisionContext
    decision: Decision
    candidate_assessments: tuple[CandidateAssessment, ...]


class DecisionFinished(Contract):
    kind: Literal["decision_finished"] = "decision_finished"
    history_entry: HistoryEntry
    next_observation: Observation | None


class InterventionRecorded(Contract):
    kind: Literal["intervention_recorded"] = "intervention_recorded"
    intervention: Intervention


class EpisodeInvalidated(Contract):
    kind: Literal["episode_invalidated"] = "episode_invalidated"
    reason: Annotated[str, Field(min_length=1)]


class EpisodeFinished(Contract):
    kind: Literal["episode_finished"] = "episode_finished"
    summary: EpisodeSummary


EventBody = Annotated[
    EpisodeStarted
    | DecisionStarted
    | DecisionFinished
    | InterventionRecorded
    | EpisodeInvalidated
    | EpisodeFinished,
    Field(discriminator="kind"),
]


class JournalEvent(Contract):
    schema_version: Literal[2] = 2
    episode_id: Identifier
    sequence: Annotated[int, Field(ge=0)]
    timestamp: Seconds
    elapsed_s: Seconds
    body: EventBody


class EpisodeJournal:
    """One exclusive file per episode. Interrupted files stay readable, never auto-resume."""

    def __init__(self, directory: Path, episode_id: str) -> None:
        TypeAdapter(Identifier).validate_python(episode_id)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{episode_id}.jsonl"
        self._file = self.path.open("x", encoding="utf-8")
        self._episode_id = episode_id
        self._sequence = 0
        self._last_elapsed = 0.0
        self._closed_episode = False

    @property
    def episode_id(self) -> str:
        return self._episode_id

    def append(self, body: EventBody, timestamp: float, elapsed_s: float) -> None:
        if self._closed_episode:
            raise RuntimeError("episode is already closed")
        if elapsed_s < self._last_elapsed:
            raise ValueError("monotonic time moved backwards")
        event = JournalEvent(
            episode_id=self._episode_id,
            sequence=self._sequence,
            timestamp=timestamp,
            elapsed_s=elapsed_s,
            body=body,
        )
        self._file.write(event.model_dump_json() + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())
        self._sequence += 1
        self._last_elapsed = elapsed_s
        self._closed_episode = isinstance(body, EpisodeFinished)

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class AuditReport(Contract):
    episodes: int
    decisions: int
    complete: bool
    errors: tuple[str, ...]
    origin: Origin | None = None
    autonomous_success: bool | None = None
    experiment_valid: bool | None = None


def _observation_evidence(observation: Observation) -> tuple[EvidenceRef, ...]:
    evidence: list[EvidenceRef] = list(observation.robot.evidence)
    for gripper in observation.grippers:
        evidence.extend(gripper.evidence)
    for obj in observation.objects:
        evidence.extend(obj.evidence)
        for relation in obj.relations:
            evidence.extend(relation.evidence)
    return tuple(evidence)


def _check_file_reference(
    uri: str, sha256: str | None, journal_path: Path, errors: list[str]
) -> None:
    evidence_path = Path(uri)
    if not evidence_path.is_absolute():
        evidence_path = journal_path.parent / evidence_path
    if not evidence_path.is_file():
        errors.append(f"missing evidence file: {uri}")
        return
    if sha256 is not None:
        digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        if digest != sha256.lower():
            errors.append(f"evidence hash mismatch: {uri}")


def audit_episode(
    path: Path, verifier_registry: VerifierRegistry = DEFAULT_VERIFIER_REGISTRY
) -> AuditReport:
    """Check journal structure, exact model inputs and evidence without inventing labels."""
    errors: list[str] = []
    pending: DecisionStarted | None = None
    seen: set[str] = set()
    started: EpisodeStarted | None = None
    ended = False
    previous_elapsed = 0.0
    verified: set[str] = set()
    latest: Observation | None = None
    final_summary: EpisodeSummary | None = None
    pending_elapsed = 0.0
    history: list[HistoryEntry] = []
    interventions: list[Intervention] = []
    exclusion_reason: str | None = None
    verifier: Verifier | None = None

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            event = JournalEvent.model_validate_json(line)
        except ValidationError:
            errors.append(f"line {line_number}: malformed event")
            continue
        expected_sequence = line_number - 1
        if event.sequence != expected_sequence or event.elapsed_s < previous_elapsed:
            errors.append(f"line {line_number}: invalid sequence or elapsed time")
        previous_elapsed = event.elapsed_s
        if ended:
            errors.append("events after episode close")
        body = event.body

        if isinstance(body, EpisodeStarted):
            if started is not None or expected_sequence != 0:
                errors.append("unexpected episode start")
            started = body
            if body.metadata.episode_id != path.stem:
                errors.append("journal filename and episode identifier mismatch")
            try:
                verifier = verifier_registry.resolve(body.metadata.manifest.verifier)
            except ValueError as exc:
                errors.append(f"auditor cannot reproduce the recorded verifier: {exc}")
        elif started is None:
            errors.append("event without episode start")
        if started is not None and event.episode_id != started.metadata.episode_id:
            errors.append("episode identifier mismatch")

        observations: tuple[Observation, ...] = ()
        evidence_refs: tuple[EvidenceRef, ...] = ()
        if isinstance(body, DecisionStarted):
            if pending is not None or body.decision_id in seen:
                errors.append("overlapping or duplicate decision")
            pending = body
            pending_elapsed = event.elapsed_s
            seen.add(body.decision_id)
            observations = (body.context.observation,)
            if body.context.history != tuple(history):
                errors.append("recorded decision context does not match prior history")
            candidate_actions = tuple(candidate.action for candidate in body.decision.candidates)
            if tuple(item.action for item in body.candidate_assessments) != candidate_actions:
                errors.append("candidate assessments do not match generated candidates")
            if started is not None:
                try:
                    for action in candidate_actions:
                        started.mission.validate_action(action)
                except ValueError as exc:
                    errors.append(str(exc))
                for assessment in body.candidate_assessments:
                    if verifier is None:
                        break
                    rejection = verifier.precondition_error(
                        started.mission,
                        assessment.action,
                        body.context.observation,
                        started.limits.max_fact_age_s,
                    )
                    if assessment.eligible != (rejection is None) or (
                        not assessment.eligible and assessment.rejection_reason != rejection
                    ):
                        errors.append("candidate eligibility does not match frozen preconditions")
        elif isinstance(body, DecisionFinished):
            entry = body.history_entry
            if pending is None or pending.decision_id != entry.decision_id:
                errors.append("result without matching decision")
            elif pending.decision.selected != entry.action:
                errors.append("finished action differs from selected action")
            if (
                pending is not None
                and abs(entry.duration_s - (event.elapsed_s - pending_elapsed)) > 1e-6
            ):
                errors.append("decision duration mismatch")
            if body.next_observation is not None:
                latest = body.next_observation
                observations = (body.next_observation,)
                if pending is not None and (
                    body.next_observation.captured_at <= pending.context.observation.captured_at
                ):
                    errors.append("next observation is not newer than decision input")
                if (
                    entry.executor_completed_at is not None
                    and body.next_observation.captured_at <= entry.executor_completed_at
                ):
                    errors.append("next observation is not newer than executor completion")
            if entry.executor_result is not None:
                evidence_refs = (*evidence_refs, *entry.executor_result.evidence)
            evidence_refs = (*evidence_refs, *entry.verification_result.evidence)
            if pending is not None and entry.verification_result.outcome == Outcome.SUCCESS:
                if body.next_observation is None or entry.executor_result is None:
                    errors.append("semantic success without execution result and observation")
                elif (
                    started is not None
                    and verifier is not None
                    and (
                        verifier.verify_action(
                            started.mission,
                            entry.action,
                            pending.context.observation,
                            body.next_observation,
                            entry.executor_result,
                            started.limits.max_fact_age_s,
                        ).outcome
                        != Outcome.SUCCESS
                    )
                ):
                    errors.append("success without verified semantic effect")
                elif entry.action.skill == "VERIFY" and started is not None:
                    action = entry.action
                    if any(
                        goal.object_id == action.object_id
                        and goal.destination.zone == action.zone
                        and goal.destination.target_id == action.target_id
                        and goal.destination.relation == action.relation
                        for goal in started.mission.goals
                    ):
                        verified.add(action.object_id or "")
            history.append(entry)
            pending = None
        elif isinstance(body, InterventionRecorded):
            interventions.append(body.intervention)
            evidence_refs = body.intervention.evidence
            if body.intervention.occurred_at > event.timestamp:
                errors.append("intervention timestamp is in the future")
        elif isinstance(body, EpisodeInvalidated):
            if exclusion_reason is not None:
                errors.append("episode invalidated more than once")
            exclusion_reason = body.reason
        elif isinstance(body, EpisodeFinished):
            final_summary = body.summary
            if pending is not None:
                errors.append("episode closed with an unfinished decision")
            if body.summary.decisions != len(seen):
                errors.append("decision count mismatch")
            if abs(body.summary.duration_s - event.elapsed_s) > 1e-6:
                errors.append("episode duration mismatch")
            if (
                body.summary.intervention_count != len(interventions)
                or abs(
                    body.summary.intervention_duration_s
                    - sum(item.duration_s for item in interventions)
                )
                > 1e-6
            ):
                errors.append("intervention summary mismatch")
            if body.summary.exclusion_reason != exclusion_reason:
                errors.append("experiment validity summary mismatch")
            if body.summary.mission_success and (
                started is None
                or latest is None
                or verified != {goal.object_id for goal in started.mission.goals}
                or verifier is None
                or not verifier.mission_complete(
                    started.mission, latest, started.limits.max_fact_age_s
                )
            ):
                errors.append("mission success without verified goals")
            ended = True

        for observation in observations:
            if observation.captured_at > event.timestamp:
                errors.append("observation from the future")
            if started is not None and observation.origin != started.metadata.origin:
                errors.append("observation origin mismatch")
            evidence_refs = (*evidence_refs, *_observation_evidence(observation))
            for frame in observation.keyframes:
                if started is not None and started.metadata.origin == Origin.PHYSICAL:
                    if frame.sha256 is None:
                        errors.append(f"physical keyframe lacks hash: {frame.path}")
                _check_file_reference(frame.path, frame.sha256, path, errors)
        for evidence in evidence_refs:
            if evidence.captured_at > event.timestamp:
                errors.append(f"evidence from the future: {evidence.evidence_id}")
            if evidence.uri is not None:
                _check_file_reference(evidence.uri, evidence.sha256, path, errors)

    if started is None:
        errors.append("missing episode start")
    if pending is not None:
        errors.append("unfinished decision")
    if not ended:
        errors.append("missing episode close")
    return AuditReport(
        episodes=int(started is not None),
        decisions=len(seen),
        complete=ended and not errors,
        errors=tuple(errors),
        origin=started.metadata.origin if started is not None else None,
        autonomous_success=(
            final_summary.autonomous_success if final_summary is not None and not errors else None
        ),
        experiment_valid=(
            final_summary.experiment_valid if final_summary is not None and not errors else None
        ),
    )
