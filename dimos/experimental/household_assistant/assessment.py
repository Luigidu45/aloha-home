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

"""Pure checks for phase-1 desk cases, not a sensor verifier or mission runner."""

import math

from dimos.experimental.household_assistant.configuration import PilotConfiguration
from dimos.experimental.household_assistant.contracts import (
    Evidence,
    ExecutionReport,
    ExecutionStage,
    FactKey,
    MissionRequest,
    Observation,
    Origin,
    Predicate,
    TargetResolution,
    Verdict,
    Verification,
)


def resolve_target(
    pilot: PilotConfiguration,
    request: MissionRequest,
    observations: tuple[Observation, ...],
    *,
    now: float,
    clock_id: str,
    max_age_s: float,
    allowed_origins: frozenset[Origin],
) -> TargetResolution:
    """Resolve registered instances using evidence, never their catalog order."""
    pilot.validate_request(request)
    candidates: list[str] = []
    unknown = False
    for obj in pilot.objects:
        if obj.category != request.object_category:
            continue
        if request.selected_object_id is not None and obj.id != request.selected_object_id:
            continue
        result = assess_requirements(
            (FactKey(subject_id=obj.id, predicate=Predicate.VISIBLE),),
            observations,
            now=now,
            clock_id=clock_id,
            max_age_s=max_age_s,
            allowed_origins=allowed_origins,
        )
        if result.verdict == Verdict.SUCCESS:
            candidates.append(obj.id)
        unknown = unknown or result.verdict == Verdict.UNKNOWN
    if len(candidates) > 1:
        return TargetResolution(status="ambiguous", candidates=tuple(candidates))
    if unknown:
        return TargetResolution(status="unknown", candidates=tuple(candidates))
    if candidates:
        return TargetResolution(status="selected", candidates=tuple(candidates))
    return TargetResolution(status="not_found", candidates=())


def assess_requirements(
    required: tuple[FactKey, ...],
    observations: tuple[Observation, ...],
    *,
    now: float,
    clock_id: str,
    max_age_s: float,
    allowed_origins: frozenset[Origin],
    after: float | None = None,
) -> Verification:
    """All supplied evidence must be usable; uncertainty never becomes success."""
    if not required or len(set(required)) != len(required):
        raise ValueError("requirements must be nonempty and unique")
    if not math.isfinite(now) or now < 0 or not math.isfinite(max_age_s) or max_age_s <= 0:
        raise ValueError("invalid assessment time or freshness limit")
    if after is not None and (not math.isfinite(after) or after < 0 or after > now):
        raise ValueError("invalid completion time")
    evidence: list[Evidence] = []
    negatives = False
    for key in required:
        matches = [item for item in observations if item.key == key]
        if len(matches) != 1:
            return Verification(verdict=Verdict.UNKNOWN, reason="missing_or_conflicting_fact")
        observation = matches[0]
        for item in observation.evidence:
            if item.clock_id != clock_id or item.origin not in allowed_origins:
                return Verification(verdict=Verdict.UNKNOWN, reason="incompatible_evidence")
            if not 0 <= now - item.captured_at <= max_age_s:
                return Verification(verdict=Verdict.UNKNOWN, reason="stale_or_future_evidence")
            if after is not None and item.captured_at <= after:
                return Verification(verdict=Verdict.UNKNOWN, reason="evidence_not_after_completion")
        if observation.value is None:
            return Verification(verdict=Verdict.UNKNOWN, reason="inconclusive_fact")
        negatives = negatives or not observation.value
        evidence.extend(observation.evidence)
    return Verification(
        verdict=Verdict.FAILURE if negatives else Verdict.SUCCESS,
        reason="requirement_false" if negatives else "requirements_confirmed",
        evidence=tuple(evidence),
    )


def assess_completion(
    execution: ExecutionReport,
    required: tuple[FactKey, ...],
    observations: tuple[Observation, ...],
    *,
    now: float,
    clock_id: str,
    max_age_s: float,
    allowed_origins: frozenset[Origin],
) -> Verification:
    """Finished motor commands require separate, fresh postcondition evidence."""
    if execution.stage != ExecutionStage.FINISHED:
        return Verification(verdict=Verdict.UNKNOWN, reason="execution_not_finished")
    if execution.clock_id != clock_id:
        return Verification(verdict=Verdict.UNKNOWN, reason="incompatible_execution_clock")
    return assess_requirements(
        required,
        observations,
        now=now,
        clock_id=clock_id,
        max_age_s=max_age_s,
        allowed_origins=allowed_origins,
        after=execution.recorded_at,
    )
