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

"""Conservative semantic checks over observed facts, never simulator-private state."""

from dimos.experimental.domestic_assistance.contracts import (
    Action,
    ExecutionResult,
    Mission,
    Observation,
    Outcome,
)


def precondition_error(action: Action, state: Observation) -> str | None:
    obj = state.object(action.object_id)
    if action.skill in {"PICK", "PLACE"} and state.base_stopped is not True:
        return "base must be observed stopped before manipulation"
    if action.skill == "PICK":
        if (
            obj is None
            or obj.visible is not True
            or state.robot_zone is None
            or obj.zone != state.robot_zone
        ):
            return "target must be observed at the robot's current zone"
        if state.grippers_empty is not True or obj.held is not False:
            return "holding state must be known and empty"
    if action.skill == "PLACE":
        if obj is None or obj.held is not True or state.robot_zone != action.zone:
            return "target must be held at the requested destination"
    return None


def verify_action(
    action: Action, before: Observation, after: Observation, result: ExecutionResult
) -> ExecutionResult:
    if result.outcome != Outcome.SUCCESS:
        return result
    obj = after.object(action.object_id)
    evidence = result.evidence
    verified = False
    if action.skill == "NAVIGATE":
        verified = (
            after.robot_zone == action.zone
            and after.base_stopped is True
            and after.captured_at > before.captured_at
            and bool(evidence)
        )
    elif obj is not None and obj.observed_at > before.captured_at and obj.evidence:
        evidence = (*evidence, *obj.evidence)
        if action.skill == "SEARCH":
            verified = obj.visible is True
        elif action.skill == "PICK":
            verified = obj.held is True
        elif action.skill in {"PLACE", "VERIFY"}:
            verified = obj.zone == action.zone and obj.held is False
    if not verified:
        return ExecutionResult(
            outcome=Outcome.UNKNOWN,
            detail="executor completed but semantic postcondition lacks evidence",
            evidence=evidence,
        )
    return ExecutionResult(outcome=Outcome.SUCCESS, detail=result.detail, evidence=evidence)


def mission_complete(mission: Mission, state: Observation) -> bool:
    return state.base_stopped is True and all(
        (obj := state.object(goal.object_id)) is not None
        and obj.zone == goal.destination
        and obj.held is False
        and bool(obj.evidence)
        for goal in mission.goals
    )
