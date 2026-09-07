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

"""Append-only episode journal. Start events are durable before executor dispatch."""

import os
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, ValidationError

from dimos.experimental.domestic_assistance.contracts import (
    Contract,
    Decision,
    EpisodeSummary,
    ExecutionResult,
    Identifier,
    Limits,
    Mission,
    Observation,
    Origin,
    Outcome,
    RunMetadata,
    Seconds,
)
from dimos.experimental.domestic_assistance.verification import mission_complete, verify_action


class EpisodeStarted(Contract):
    kind: Literal["episode_started"] = "episode_started"
    mission: Mission
    metadata: RunMetadata
    limits: Limits


class DecisionStarted(Contract):
    kind: Literal["decision_started"] = "decision_started"
    decision_id: Identifier
    observation: Observation
    decision: Decision


class DecisionFinished(Contract):
    kind: Literal["decision_finished"] = "decision_finished"
    decision_id: Identifier
    result: ExecutionResult
    execution_result: ExecutionResult | None = None
    next_observation: Observation | None
    duration_s: Seconds


class EpisodeFinished(Contract):
    kind: Literal["episode_finished"] = "episode_finished"
    summary: EpisodeSummary


EventBody = Annotated[
    EpisodeStarted | DecisionStarted | DecisionFinished | EpisodeFinished,
    Field(discriminator="kind"),
]


class JournalEvent(Contract):
    schema_version: Literal[1] = 1
    episode_id: Identifier
    sequence: Annotated[int, Field(ge=0)]
    timestamp: Seconds
    elapsed_s: Seconds
    body: EventBody


class EpisodeJournal:
    """One exclusive file per episode. Interrupted files stay readable, never auto-resume."""

    def __init__(self, directory: Path, episode_id: str) -> None:
        # Validate the identifier before using it in a file name.
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


def audit_episode(path: Path) -> AuditReport:
    """Check journal structure and evidence paths; incomplete missions have no success label."""
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
    for sequence, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        try:
            event = JournalEvent.model_validate_json(line)
        except ValidationError:
            errors.append(f"line {sequence + 1}: malformed event")
            continue
        if event.sequence != sequence or event.elapsed_s < previous_elapsed:
            errors.append(f"line {sequence + 1}: invalid sequence or elapsed time")
        previous_elapsed = event.elapsed_s
        if ended:
            errors.append("events after episode close")
        body = event.body
        if isinstance(body, EpisodeStarted):
            if started is not None or sequence != 0:
                errors.append("unexpected episode start")
            started = body
        elif started is None:
            errors.append("event without episode start")
        if started is not None and event.episode_id != started.metadata.episode_id:
            errors.append("episode identifier mismatch")
        observations: tuple[Observation, ...] = ()
        if isinstance(body, DecisionStarted):
            if pending is not None or body.decision_id in seen:
                errors.append("overlapping or duplicate decision")
            pending = body
            pending_elapsed = event.elapsed_s
            seen.add(body.decision_id)
            observations = (body.observation,)
            if body.decision.selected.skill in {"PICK", "PLACE"}:
                verified.discard(body.decision.selected.object_id or "")
            if started is not None:
                try:
                    for action in body.decision.candidates:
                        started.mission.validate_action(action)
                except ValueError as exc:
                    errors.append(str(exc))
        elif isinstance(body, DecisionFinished):
            if pending is None or pending.decision_id != body.decision_id:
                errors.append("result without matching decision")
            if (
                pending is not None
                and abs(body.duration_s - (event.elapsed_s - pending_elapsed)) > 1e-6
            ):
                errors.append("decision duration mismatch")
            if body.next_observation is not None:
                latest = body.next_observation
                observations = (body.next_observation,)
                if pending is not None and (
                    body.next_observation.captured_at < pending.observation.captured_at
                ):
                    errors.append("next observation predates decision")
            if pending is not None and body.result.outcome == Outcome.SUCCESS:
                if body.next_observation is None or body.execution_result is None:
                    errors.append("success without execution result and observation")
                elif (
                    verify_action(
                        pending.decision.selected,
                        pending.observation,
                        body.next_observation,
                        body.execution_result,
                    ).outcome
                    != Outcome.SUCCESS
                ):
                    errors.append("success without verified semantic effect")
                elif pending.decision.selected.skill == "VERIFY" and started is not None:
                    action = pending.decision.selected
                    if any(
                        goal.object_id == action.object_id and goal.destination == action.zone
                        for goal in started.mission.goals
                    ):
                        verified.add(action.object_id or "")
            pending = None
        elif isinstance(body, EpisodeFinished):
            final_summary = body.summary
            if pending is not None:
                errors.append("episode closed with an unfinished decision")
            if body.summary.decisions != len(seen):
                errors.append("decision count mismatch")
            if abs(body.summary.duration_s - event.elapsed_s) > 1e-6:
                errors.append("episode duration mismatch")
            if body.summary.autonomous_success and (
                started is None
                or latest is None
                or verified != {goal.object_id for goal in started.mission.goals}
                or not mission_complete(started.mission, latest)
            ):
                errors.append("mission success without verified goals")
            ended = True
        for observation in observations:
            if observation.captured_at > event.timestamp:
                errors.append("observation from the future")
            if started is not None and observation.origin != started.metadata.origin:
                errors.append("observation origin mismatch")
            for frame in observation.keyframes:
                evidence_path = Path(frame.path)
                if not evidence_path.is_absolute():
                    evidence_path = path.parent / evidence_path
                if not evidence_path.is_file():
                    errors.append(f"missing keyframe: {frame.path}")
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
    )
