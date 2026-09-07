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

"""Versioned semantic contracts, independent of robot drivers and model backends."""

from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, pattern=r"^[a-zA-Z0-9_.-]+$")]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Origin(str, Enum):
    TEST = "test"
    SIMULATION = "simulation"
    PHYSICAL = "physical"


class Outcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


class Action(Contract):
    """Closed semantic vocabulary; no arbitrary executor commands or extra arguments."""

    skill: Literal["NAVIGATE", "SEARCH", "VERIFY", "PICK", "PLACE", "ASK", "ABORT"]
    object_id: Identifier | None = None
    zone: Identifier | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_arguments(self) -> Self:
        required = {
            "NAVIGATE": {"zone"},
            "SEARCH": {"object_id"},
            "VERIFY": {"object_id", "zone"},
            "PICK": {"object_id"},
            "PLACE": {"object_id", "zone"},
            "ASK": {"reason"},
            "ABORT": {"reason"},
        }[self.skill]
        supplied = {
            name for name in ("object_id", "zone", "reason") if getattr(self, name) is not None
        }
        if supplied != required:
            raise ValueError(f"{self.skill} requires exactly {sorted(required)}")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("reason must not be blank")
        return self


class Goal(Contract):
    object_id: Identifier
    destination: Identifier


class Mission(Contract):
    task_id: Identifier
    instruction: Annotated[str, Field(min_length=1)]
    zones: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    goals: Annotated[tuple[Goal, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_goals(self) -> Self:
        if len(set(self.zones)) != len(self.zones):
            raise ValueError("zones must be unique")
        if len({goal.object_id for goal in self.goals}) != len(self.goals):
            raise ValueError("each object must have exactly one goal")
        if any(goal.destination not in self.zones for goal in self.goals):
            raise ValueError("goal destination is not a registered zone")
        return self

    def validate_action(self, action: Action) -> None:
        if action.zone is not None and action.zone not in self.zones:
            raise ValueError("action references an unregistered zone")
        if action.object_id is not None and action.object_id not in {
            goal.object_id for goal in self.goals
        }:
            raise ValueError("action references an unregistered object")


class Keyframe(Contract):
    path: Annotated[str, Field(min_length=1)]
    camera: Identifier
    captured_at: Seconds


class ObjectObservation(Contract):
    object_id: Identifier
    zone: Identifier | None = None
    visible: bool | None = None
    held: bool | None = None
    observed_at: Seconds
    evidence: tuple[str, ...] = ()


class Observation(Contract):
    """Only information available before choosing the next action; no terminal label."""

    captured_at: Seconds
    origin: Origin
    robot_zone: Identifier | None = None
    base_stopped: bool | None = None
    grippers_empty: bool | None = None
    objects: tuple[ObjectObservation, ...] = ()
    keyframes: tuple[Keyframe, ...] = ()

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        if len({obj.object_id for obj in self.objects}) != len(self.objects):
            raise ValueError("duplicate object observations")
        if any(obj.observed_at > self.captured_at for obj in self.objects):
            raise ValueError("object observation is from the future")
        if any(frame.captured_at > self.captured_at for frame in self.keyframes):
            raise ValueError("keyframe is from the future")
        return self

    def object(self, object_id: str | None) -> ObjectObservation | None:
        return next((obj for obj in self.objects if obj.object_id == object_id), None)


class ExecutionResult(Contract):
    """Executor completion, distinct from verification of its semantic effect."""

    outcome: Outcome
    detail: str
    evidence: tuple[str, ...] = ()


class Decision(Contract):
    candidates: Annotated[tuple[Action, ...], Field(min_length=1, max_length=3)]
    selected: Action
    behavior: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def selected_is_candidate(self) -> Self:
        if self.selected not in self.candidates:
            raise ValueError("selected action must occur in candidates")
        return self


class Limits(Contract):
    max_decisions: Annotated[int, Field(gt=0)] = 20
    max_consecutive_attempts: Annotated[int, Field(gt=0)] = 2
    mission_timeout_s: Annotated[float, Field(gt=0)] = 480.0
    skill_timeout_s: Annotated[float, Field(gt=0)] = 30.0
    cancellation_timeout_s: Annotated[float, Field(gt=0)] = 5.0
    max_observation_age_s: Annotated[float, Field(gt=0)] = 2.0


class RunMetadata(Contract):
    episode_id: Identifier
    scenario_id: Identifier
    session_id: Identifier
    split_group: Identifier
    seed: int
    origin: Origin
    code_version: Annotated[str, Field(min_length=1)]
    supervisor_version: Annotated[str, Field(min_length=1)]
    executor_version: Annotated[str, Field(min_length=1)]
    verifier_version: Annotated[str, Field(min_length=1)]


class EpisodeSummary(Contract):
    reason: Literal[
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
    autonomous_success: bool
    assistance_requested: bool = False
    decisions: Annotated[int, Field(ge=0)]
    duration_s: Seconds
    detail: str = ""

    @model_validator(mode="after")
    def validate_success(self) -> Self:
        if self.autonomous_success != (self.reason == "SUCCESS"):
            raise ValueError("success label contradicts termination reason")
        if self.autonomous_success and self.assistance_requested:
            raise ValueError("an assisted mission is not autonomous success")
        return self
