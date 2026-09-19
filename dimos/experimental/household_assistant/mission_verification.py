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

"""Executable F4 requirements, distinct from the human-readable F1 skill descriptions."""

from dimos.experimental.household_assistant.contracts import (
    ActionProposal,
    FactKey,
    MissionRequest,
    Operation,
    Predicate,
)
from dimos.experimental.household_assistant.mission_contracts import Arm


def fact(
    subject: str, predicate: Predicate, place: str | None = None, arm: Arm | None = None
) -> FactKey:
    return FactKey(subject_id=subject, predicate=predicate, place_id=place, arm=arm)


def stopped() -> tuple[FactKey, ...]:
    return tuple(fact(s, Predicate.STOPPED) for s in ("base", "elevator", "left_arm", "right_arm"))


def empty() -> tuple[FactKey, ...]:
    return (
        fact("gripper", Predicate.EMPTY, arm="left"),
        fact("gripper", Predicate.EMPTY, arm="right"),
    )


def carrying(object_id: str, arm: Arm) -> tuple[FactKey, ...]:
    return (
        fact(object_id, Predicate.HELD, arm=arm),
        fact(object_id, Predicate.TRANSPORT_READY, arm=arm),
    )


def preconditions(
    operation: Operation,
    action: ActionProposal,
    request: MissionRequest,
    held: str | None,
    arm: Arm,
) -> tuple[FactKey, ...]:
    required = list(stopped())
    if operation == Operation.NAVIGATE:
        required.extend(carrying(held, arm) if held else empty())
    else:
        required.append(fact("base", Predicate.AT, action.destination_id))
    if operation == Operation.ALIGN:
        required.extend(carrying(held, arm) if held else empty())
    if operation == Operation.PICK:
        assert action.object_id is not None
        required.extend(empty())
        required.extend(
            (
                fact("base", Predicate.ALIGNED, request.source_id),
                fact(action.object_id, Predicate.VISIBLE),
                fact(action.object_id, Predicate.AT, request.source_id),
            )
        )
    if operation in (Operation.STOW, Operation.PLACE):
        assert action.object_id is not None
        required.append(fact(action.object_id, Predicate.HELD, arm=arm))
    if operation == Operation.PLACE:
        required.extend(
            (
                fact("base", Predicate.ALIGNED, request.destination_id),
                fact(request.destination_id, Predicate.CLEAR),
            )
        )
    return tuple(required)


def postconditions(
    operation: Operation, action: ActionProposal, held: str | None, arm: Arm
) -> tuple[FactKey, ...]:
    required = list(stopped())
    if operation == Operation.NAVIGATE:
        required.append(fact("base", Predicate.AT, action.destination_id))
        if held:
            required.extend(carrying(held, arm))
    elif operation == Operation.ALIGN:
        required.append(fact("base", Predicate.ALIGNED, action.destination_id))
        if held:
            required.append(fact(held, Predicate.HELD, arm=arm))
    elif operation in (Operation.PICK, Operation.STOW, Operation.PLACE):
        assert action.object_id is not None
        if operation == Operation.PICK:
            required.append(fact(action.object_id, Predicate.HELD, arm=arm))
        elif operation == Operation.STOW:
            required.extend(carrying(action.object_id, arm))
        else:
            required.extend(
                (
                    fact(action.object_id, Predicate.INSIDE, action.destination_id),
                    fact(action.object_id, Predicate.RELEASED, arm=arm),
                    fact(action.object_id, Predicate.STABLE),
                    fact("gripper", Predicate.EMPTY, arm=arm),
                )
            )
    # OBSERVE verifies fresh stopped-at-station evidence, not positive object detection.
    elif operation == Operation.OBSERVE:
        required.append(fact("base", Predicate.AT, action.destination_id))
    return tuple(required)
