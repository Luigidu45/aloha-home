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

"""Messages at the F4 dispatcher boundary; none of these activate hardware."""

from typing import Annotated, Literal

from pydantic import Field

from dimos.experimental.household_assistant.contracts import (
    ActionProposal,
    Contract,
    Evidence,
    Identifier,
    MissionRequest,
    Observation,
    Operation,
    Origin,
    Text,
    Timestamp,
    Verification,
)

Arm = Literal["left", "right"]
MissionState = Literal[
    "idle",
    "preparing",
    "searching",
    "navigating",
    "manipulating",
    "verifying",
    "asking",
    "stopping",
    "stop_unconfirmed",
    "paused",
    "cancelled",
    "failed",
    "succeeded",
]


class ExecutorBinding(Contract):
    id: Identifier
    operations: tuple[Operation, ...]
    origin: Origin
    artificial: bool


class WorldFrame(Contract):
    """Full authoritative snapshot, not a delta. A revision changes with the scene/robot.

    Refreshing this envelope does not refresh timestamps in its observations.
    Camera evidence is keyed by configured camera alias, with capture provenance.
    """

    revision: Annotated[int, Field(ge=0)]
    captured_at: Timestamp
    clock_id: Identifier
    connected: bool
    observations: tuple[Observation, ...]
    cameras: dict[str, Evidence] = Field(default_factory=dict)


class ExecutorCommand(Contract):
    kind: Literal["start", "stop"]
    executor_id: Identifier
    action: ActionProposal
    issued_at: Timestamp
    clock_id: Identifier


class ExecutorResult(Contract):
    executor_id: Identifier
    action_id: Identifier
    stage: Literal["running", "finished", "failed", "stopped"]
    recorded_at: Timestamp
    clock_id: Identifier
    detail: Text


class MissionEvent(Contract):
    sequence: int
    request_id: str
    action_id: str | None = None
    at: Timestamp
    clock_id: Identifier
    kind: Text
    detail: Text
    state: MissionState
    verification: Verification | None = None
    command: ExecutorCommand | None = None


class MissionSnapshot(Contract):
    request_id: str = ""
    state: MissionState = "idle"
    reason: str = "not_started"
    action: ActionProposal | None = None
    revision: int = -1
    selected_object_id: str | None = None
    held_object_id: str | None = None
    arm: Arm = "right"
    verification: Verification | None = None
    stop_verification: Verification | None = None
    stop_requested_at: float | None = None
    stop_confirmed_at: float | None = None
    completed_actions: tuple[str, ...] = ()


class MissionPlanningState(Contract):
    request: MissionRequest | None
    state: MissionSnapshot
    world: WorldFrame | None
