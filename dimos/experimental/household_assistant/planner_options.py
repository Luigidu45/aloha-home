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

"""State-dependent skill admission candidates, not an action sequence or visual recognizer."""

import re

from dimos.experimental.household_assistant.assessment import assess_requirements, resolve_target
from dimos.experimental.household_assistant.configuration import PilotConfiguration
from dimos.experimental.household_assistant.contracts import (
    ActionProposal,
    FactKey,
    Operation,
    Origin,
    Predicate,
    Verdict,
)
from dimos.experimental.household_assistant.mission_verification import fact, preconditions
from dimos.experimental.household_assistant.planner_contracts import PlannerContext


def missing_request_slots(instruction: str) -> tuple[str, ...]:
    """Conservative Spanish scope gate; a visible bottle cannot fill an omitted request slot."""
    words = set(re.findall(r"\w+", instruction.casefold()))
    missing = []
    if not words.intersection({"botella", "botellita"}):
        missing.append("object")
    if not words.intersection({"dormitorio", "habitación", "habitacion", "mesa_dormitorio"}):
        missing.append("destination")
    return tuple(missing)


def available_actions(
    pilot: PilotConfiguration, context: PlannerContext, *, max_age_s: float
) -> tuple[ActionProposal, ...]:
    request = context.request
    if request is None:
        return ()
    state, frame = context.state, context.world
    now = frame.captured_at

    def confirmed(key: FactKey) -> bool:
        return (
            assess_requirements(
                (key,),
                frame.observations,
                now=now,
                clock_id=frame.clock_id,
                max_age_s=max_age_s,
                allowed_origins=frozenset({Origin.TEST, Origin.SIMULATION}),
            ).verdict
            == Verdict.SUCCESS
        )

    resolved = resolve_target(
        pilot,
        request,
        frame.observations,
        now=now,
        clock_id=frame.clock_id,
        max_age_s=max_age_s,
        allowed_origins=frozenset({Origin.TEST, Origin.SIMULATION}),
    )
    target = state.selected_object_id or (
        resolved.candidates[0] if resolved.status == "selected" else None
    )
    held = state.held_object_id
    destination = request.destination_id if held else request.source_id
    actions = []
    for skill in context.catalog:
        if skill.id == "pick_remote_from_floor":
            continue
        object_id = None
        place = destination
        if skill.operation == Operation.NAVIGATE and confirmed(
            fact("base", Predicate.AT, destination)
        ):
            continue  # Already there: no duplicate navigation as a substitute for observing.
        if skill.operation == Operation.OBSERVE:
            if not confirmed(fact("base", Predicate.AT, destination)):
                continue
            if state.completed_actions.count("observe_at") >= 2:
                continue
        if skill.operation == Operation.ALIGN:
            if confirmed(fact("base", Predicate.ALIGNED, destination)) or (not held and not target):
                continue
        if skill.operation == Operation.PICK:
            if not target or held:
                continue
            object_id, place = target, request.source_id
        if skill.operation == Operation.STOW:
            if not held or confirmed(fact(held, Predicate.TRANSPORT_READY, arm=state.arm)):
                continue
            object_id = held
            place = (
                request.destination_id
                if confirmed(fact("base", Predicate.AT, request.destination_id))
                else request.source_id
            )
        if skill.operation == Operation.PLACE:
            if not held:
                continue
            object_id = held
        action = ActionProposal(
            id="admission_candidate",
            request_id=request.id,
            skill_id=skill.id,
            destination_id=place,
            object_id=object_id,
            arm=state.arm if object_id else None,
        )
        required = preconditions(skill.operation, action, request, held, state.arm)
        if not all(confirmed(key) for key in required):
            continue
        if any(
            name not in frame.cameras
            or frame.cameras[name].clock_id != frame.clock_id
            or not 0 <= now - frame.cameras[name].captured_at <= max_age_s
            for name in skill.required_cameras
        ):
            continue
        actions.append(action)
    return tuple(actions)


def needs_visual_clarification(
    count: str, *, at_source: bool, held: str | None, selected: str | None
) -> bool:
    """Negative visual veto; never evidence of instance identity or grasp success."""
    return (
        at_source
        and held is None
        and (count in {"0", "unknown"} or (count == "2" and selected is None))
    )
