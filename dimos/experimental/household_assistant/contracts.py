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

"""Phase-1 semantic contracts. No drivers, models, execution or global registries."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
Text = Annotated[str, Field(min_length=1)]
Timestamp = Annotated[float, Field(ge=0)]
Positive = Annotated[float, Field(gt=0)]


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, allow_inf_nan=False, str_strip_whitespace=True
    )


class Origin(StrEnum):
    TEST = "test"
    SIMULATION = "simulation"
    EXTERNAL_RECORDING = "external_recording"
    PHYSICAL = "physical"


class Evidence(Contract):
    origin: Origin
    source: Text
    reference: Text
    captured_at: Timestamp
    clock_id: Identifier
    frame_id: Text


class Predicate(StrEnum):
    VISIBLE = "visible"
    AT = "at"
    INSIDE = "inside"
    HELD = "held"
    RELEASED = "released"
    STOPPED = "stopped"
    ALIGNED = "aligned"
    TRANSPORT_READY = "transport_ready"
    EMPTY = "empty"
    CLEAR = "clear"
    STABLE = "stable"


class FactKey(Contract):
    subject_id: Identifier
    predicate: Predicate
    place_id: Identifier | None = None
    arm: Literal["left", "right"] | None = None

    @model_validator(mode="after")
    def spatial_reference(self) -> Self:
        spatial = self.predicate in {Predicate.AT, Predicate.INSIDE, Predicate.ALIGNED}
        if spatial != (self.place_id is not None):
            raise ValueError("only spatial predicates require a place_id")
        arm_specific = self.predicate in {
            Predicate.HELD,
            Predicate.RELEASED,
            Predicate.TRANSPORT_READY,
            Predicate.EMPTY,
        }
        if arm_specific != (self.arm is not None):
            raise ValueError("holding, release and transport posture require an arm")
        return self


class Observation(Contract):
    key: FactKey
    value: StrictBool | None
    evidence: Annotated[tuple[Evidence, ...], Field(min_length=1)]


class RegionGeometry(Contract):
    """Measured acceptance rectangle in a surface frame, in metres."""

    frame_id: Text
    center_x_m: float
    center_y_m: float
    width_m: Positive
    depth_m: Positive
    surface_height_m: Timestamp
    measurement_source: Text


class Place(Contract):
    id: Identifier
    name: Text
    room: Text
    role: Literal["pickup", "floor_pickup", "delivery"]
    geometry: RegionGeometry | None = None
    accessibility_confirmed: bool = False

    @model_validator(mode="after")
    def confirmed_region_is_measured(self) -> Self:
        if self.accessibility_confirmed and (self.role != "delivery" or self.geometry is None):
            raise ValueError("accessible delivery requires measured delivery geometry")
        return self


class ObjectDefinition(Contract):
    id: Identifier
    category: Identifier
    description: Text


class Operation(StrEnum):
    OBSERVE = "observe"
    NAVIGATE = "navigate"
    ALIGN = "align"
    PICK = "pick"
    STOW = "stow"
    PLACE = "place"


class SkillDefinition(Contract):
    id: Identifier
    description: Text
    operation: Operation
    executor_id: Identifier
    object_categories: tuple[Identifier, ...] = ()
    pickup_role: Literal["pickup", "floor_pickup"] | None = None
    compatible_scene: Text
    required_cameras: tuple[Identifier, ...] = ()
    preconditions: Annotated[tuple[Text, ...], Field(min_length=1)]
    postconditions: Annotated[tuple[Text, ...], Field(min_length=1)]
    timeout_s: Positive
    cancellation: Literal["confirm_stop", "cancel_pending_actions_and_confirm_stop"]
    pause: Literal["cancel_and_reprepare"]
    implementation: Literal["planned"] = "planned"

    @model_validator(mode="after")
    def manipulation_domain(self) -> Self:
        if (
            self.operation in {Operation.PICK, Operation.STOW, Operation.PLACE}
            and not self.object_categories
        ):
            raise ValueError("manipulation skills require an explicit object domain")
        if (self.operation == Operation.PICK) != (self.pickup_role is not None):
            raise ValueError("only pick skills require a pickup_role")
        return self


class TransportDefinition(Contract):
    mode: Literal["held_in_gripper"]
    posture_id: Identifier
    arm: Literal["left", "right"] | None = None
    physically_validated: bool = False


class MissionDefinition(Contract):
    id: Identifier
    object_category: Identifier
    source_id: Identifier
    destination_id: Identifier
    pickup_skill_id: Identifier
    user_profile: Text


class MissionRequest(Contract):
    """Normalized request; parsing the original instruction belongs to later phases."""

    id: Identifier
    mission_id: Identifier
    instruction: Text
    object_category: Identifier
    source_id: Identifier
    destination_id: Identifier
    selected_object_id: Identifier | None = None


class ActionProposal(Contract):
    id: Identifier
    request_id: Identifier
    skill_id: Identifier
    destination_id: Identifier
    object_id: Identifier | None = None
    arm: Literal["left", "right"] | None = None


class ExecutionStage(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


class ExecutionReport(Contract):
    action_id: Identifier
    stage: ExecutionStage
    recorded_at: Timestamp
    clock_id: Identifier
    detail: Text


class Verdict(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNKNOWN = "unknown"


class Verification(Contract):
    verdict: Verdict
    reason: Text
    evidence: tuple[Evidence, ...] = ()

    @model_validator(mode="after")
    def conclusive_verdict_has_evidence(self) -> Self:
        if self.verdict != Verdict.UNKNOWN and not self.evidence:
            raise ValueError("a conclusive verdict requires evidence")
        return self


class TargetResolution(Contract):
    status: Literal["selected", "ambiguous", "not_found", "unknown"]
    candidates: tuple[Identifier, ...]
