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

"""Validate a pilot definition and proposed actions without activating executors."""

from collections.abc import Collection
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from dimos.experimental.household_assistant.contracts import (
    ActionProposal,
    Contract,
    MissionDefinition,
    MissionRequest,
    ObjectDefinition,
    Operation,
    Place,
    SkillDefinition,
    TransportDefinition,
)


class PilotConfiguration(Contract):
    schema_version: Literal[1] = 1
    mission: MissionDefinition
    expansion: MissionDefinition
    transport: TransportDefinition
    places: Annotated[tuple[Place, ...], Field(min_length=3)]
    objects: Annotated[tuple[ObjectDefinition, ...], Field(min_length=1)]
    skills: Annotated[tuple[SkillDefinition, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def references(self) -> Self:
        for items in (self.places, self.objects, self.skills):
            if len({item.id for item in items}) != len(items):
                raise ValueError("duplicate catalog identifiers")
        categories = {item.category for item in self.objects}
        roles = {item.id: item.role for item in self.places}
        if self.mission.id == self.expansion.id:
            raise ValueError("mission and expansion identifiers must differ")
        for mission, role in ((self.mission, "pickup"), (self.expansion, "floor_pickup")):
            if mission.object_category not in categories:
                raise ValueError("unknown mission object category")
            if (
                roles.get(mission.source_id) != role
                or roles.get(mission.destination_id) != "delivery"
            ):
                raise ValueError("mission requires matching pickup and delivery places")
            pickup = self.skill(mission.pickup_skill_id)
            if pickup.operation != Operation.PICK or pickup.pickup_role != role:
                raise ValueError("mission requires a compatible pickup skill")
            if mission.object_category not in pickup.object_categories:
                raise ValueError("mission object outside pickup skill domain")
        for skill in self.skills:
            if not set(skill.object_categories) <= categories:
                raise ValueError("unknown skill object category")
        return self

    def skill(self, skill_id: str) -> SkillDefinition:
        for skill in self.skills:
            if skill.id == skill_id:
                return skill
        raise ValueError(f"unknown skill: {skill_id}")

    def validate_request(self, request: MissionRequest) -> None:
        roles = {item.id: item.role for item in self.places}
        if roles.get(request.source_id) not in {"pickup", "floor_pickup"}:
            raise ValueError("unknown pickup location")
        return_to_source = (
            request.mission_id == self.mission.id
            and request.destination_id == self.mission.source_id
        )
        if roles.get(request.destination_id) != "delivery" and not return_to_source:
            raise ValueError("unknown delivery region")
        candidates = [item for item in self.objects if item.category == request.object_category]
        if not candidates:
            raise ValueError("unknown requested object category")
        mission = next(
            (item for item in (self.mission, self.expansion) if item.id == request.mission_id), None
        )
        if mission is None:
            raise ValueError("unknown mission")
        if (request.source_id, request.object_category) != (
            mission.source_id,
            mission.object_category,
        ) or request.destination_id not in (
            (mission.destination_id, mission.source_id)
            if mission.id == self.mission.id
            else (mission.destination_id,)
        ):
            raise ValueError("request is outside the configured mission")
        if request.selected_object_id is not None and request.selected_object_id not in {
            item.id for item in candidates
        }:
            raise ValueError("selected object does not match request")

    def validate_action(
        self,
        request: MissionRequest,
        action: ActionProposal,
        *,
        available_executor_ids: Collection[str],
    ) -> SkillDefinition:
        """Check structural admission; F4 must bind real executors and check live state."""
        self.validate_request(request)
        if action.request_id != request.id:
            raise ValueError("action belongs to a different request")
        skill = self.skill(action.skill_id)
        if skill.executor_id not in available_executor_ids:
            raise ValueError("skill has no available executor")
        places = {item.id: item for item in self.places}
        if action.destination_id not in places:
            raise ValueError("unknown action destination")
        if action.destination_id not in {request.source_id, request.destination_id}:
            raise ValueError("action destination is outside this mission")
        if skill.operation in {Operation.NAVIGATE, Operation.OBSERVE, Operation.ALIGN}:
            if action.object_id is not None or action.arm is not None:
                raise ValueError("only manipulation accepts object and arm parameters")
            return skill
        obj = next((item for item in self.objects if item.id == action.object_id), None)
        if obj is None or obj.category != request.object_category:
            raise ValueError("manipulation target does not match request")
        if obj.category not in skill.object_categories:
            raise ValueError("object outside declared skill domain")
        if request.selected_object_id is not None and obj.id != request.selected_object_id:
            raise ValueError("manipulation target differs from user selection")
        if action.arm is None:
            raise ValueError("manipulation requires an explicit arm")
        if self.transport.arm is not None and action.arm != self.transport.arm:
            raise ValueError("arm differs from configured transport arm")
        if skill.operation == Operation.PICK:
            if (
                action.destination_id != request.source_id
                or places[action.destination_id].role != skill.pickup_role
            ):
                raise ValueError("pickup does not match skill domain and mission source")
        if skill.operation == Operation.PLACE and action.destination_id != request.destination_id:
            raise ValueError("placement must target the requested delivery region")
        return skill


def load_pilot(path: Path) -> PilotConfiguration:
    return PilotConfiguration.model_validate_json(path.read_text())
