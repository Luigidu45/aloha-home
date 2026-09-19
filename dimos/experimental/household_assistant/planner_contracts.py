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

"""Bounded F5 inputs and outputs. Model text is never executable authority."""

from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from dimos.experimental.household_assistant.contracts import (
    Contract,
    Identifier,
    MissionRequest,
    SkillDefinition,
    Text,
)
from dimos.experimental.household_assistant.mission_contracts import MissionSnapshot, WorldFrame
from dimos.experimental.household_assistant.semantic_memory import MemoryCandidate
from dimos.experimental.household_assistant.visual import ObservedView, VisualObservation

PlannerSkill = Literal[
    "navigate_to",
    "observe_at",
    "align_at",
    "pick_bottle_from_table",
    "prepare_transport",
    "place_on_table",
]


class PlannerDecision(Contract):
    kind: Literal["request", "action", "ask"]
    skill: PlannerSkill | None = None
    destination: Literal["mesa_sala", "mesa_dormitorio"] | None = None
    object_id: Literal["bottle_01", "bottle_02"] | None = None
    question: str | None = Field(default=None, max_length=400)
    reason: Annotated[str, Field(min_length=1, max_length=400)] = "model_proposal"
    plan: Annotated[tuple[PlannerSkill, ...], Field(max_length=12)] = ()
    views: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=2)]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.kind == "ask":
            if not self.question or self.skill or self.object_id or self.destination:
                raise ValueError("question must not include executable parameters")
        elif self.question is not None:
            raise ValueError("action/request must not include a question")
        if self.kind == "request" and (
            self.skill is not None
            or self.object_id is not None
            or self.destination != "mesa_dormitorio"
        ):
            raise ValueError("only the confirmed mission A destination is supported")
        if self.kind == "action":
            if self.skill is None or self.destination is None:
                raise ValueError("action requires skill and destination")
            manipulation = self.skill in {
                "pick_bottle_from_table",
                "prepare_transport",
                "place_on_table",
            }
            if manipulation != (self.object_id is not None):
                raise ValueError("only manipulation requires a logical object")
        return self


class PlannerContext(Contract):
    instruction: Annotated[str, Field(min_length=1, max_length=1000)]
    request: MissionRequest | None
    state: MissionSnapshot
    world: WorldFrame
    views: Annotated[tuple[ObservedView, ...], Field(min_length=1, max_length=2)]
    memory: tuple[MemoryCandidate, ...] = ()
    perception: tuple[VisualObservation, ...] = ()
    catalog: tuple[SkillDefinition, ...]
    previous_result: Text


class PixelReceipt(Contract):
    view_id: Identifier
    rgb_sha256: str
    png_sha256: str


class BackendReply(Contract):
    raw: str
    receipts: tuple[PixelReceipt, ...]
    tensor_sha256: str
    tensor_shape: tuple[int, ...]
    elapsed_s: float
    peak_rss_mib: float
    generated_tokens: int
    visual_assessment: Literal["0", "1", "2", "unknown"]
    visual_elapsed_s: float = 0
    visual_clarification_required: bool = False


class PlannerConfig(Contract):
    schema_version: Literal[1] = 1
    model_id: Text
    revision: Text
    device: Literal["cpu", "cuda"] = "cpu"
    dtype: Literal["bfloat16", "float32", "float16"] = "bfloat16"
    cpu_threads: Annotated[int, Field(ge=1, le=16)] = 4
    max_new_tokens: Annotated[int, Field(ge=32, le=512)] = 220
    max_pixels: Annotated[int, Field(ge=784, le=1000000)] = 200704
    timeout_s: Annotated[float, Field(gt=0, le=60)] = 60
    startup_timeout_s: Annotated[float, Field(gt=0, le=300)] = 120
    max_image_age_s: Annotated[float, Field(gt=0, le=5)] = 2
    prompt_version: Literal["household-f5-v1"] = "household-f5-v1"


def generation_schema() -> dict[str, Any]:
    """Constrain JSON syntax/domain; cross-field and mission checks remain mandatory."""
    schema = PlannerDecision.model_json_schema()
    schema["properties"]["plan"]["maxItems"] = 3
    return schema
