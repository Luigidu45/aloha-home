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

"""F7 data boundary. Artificial units cannot be used as hardware calibration."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, model_validator
from typing_extensions import Self

from dimos.experimental.household_assistant.contracts import Contract


class ACTProfile(Contract):
    schema_version: Literal[1] = 1
    platform: Literal["alohamini1"] = "alohamini1"
    provenance: Literal["artificial_pipeline_only"] = "artificial_pipeline_only"
    skill_id: Literal["pick_bottle_from_table", "place_on_table"]
    executor_id: Literal["act_pick_table", "act_place"]
    arm: Literal["right"] = "right"
    axes: tuple[str, ...]
    units: Literal["synthetic_normalized_not_motor_units"] = "synthetic_normalized_not_motor_units"
    cameras: tuple[str, ...] = ("top_rgb", "right_wrist_rgb", "left_wrist_rgb")
    image_hw: tuple[int, int] = (128, 128)
    fps: Annotated[int, Field(ge=1, le=60)] = 10
    chunk_size: Annotated[int, Field(ge=1, le=100)] = 4
    execute_steps: Annotated[int, Field(ge=1)] = 2
    max_age_s: Annotated[float, Field(gt=0)] = 0.2
    max_skew_s: Annotated[float, Field(gt=0)] = 0.05
    prediction_ttl_s: Annotated[float, Field(gt=0)] = 0.5
    inference_timeout_s: Annotated[float, Field(gt=0)] = 10.0
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    max_step: tuple[float, ...]
    clock_id: Literal["unix"] = "unix"

    @model_validator(mode="after")
    def dimensions(self) -> Self:
        n = len(self.axes)
        if not n or len(set(self.axes)) != n:
            raise ValueError("axes must be unique and nonempty")
        if not self.cameras or len(set(self.cameras)) != len(self.cameras):
            raise ValueError("cameras must be unique and nonempty")
        if min(self.image_hw) < 32 or self.execute_steps > self.chunk_size:
            raise ValueError("invalid image/chunk dimensions")
        if any(len(x) != n for x in (self.lower, self.upper, self.max_step)):
            raise ValueError("axis bounds have incompatible dimensions")
        if any(
            lo >= hi or step <= 0
            for lo, hi, step in zip(self.lower, self.upper, self.max_step, strict=True)
        ):
            raise ValueError("invalid bounds")
        expected = "act_pick_table" if self.skill_id == "pick_bottle_from_table" else "act_place"
        if self.executor_id != expected:
            raise ValueError("skill and executor differ")
        return self

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(), sort_keys=True).encode()).hexdigest()


def load_act_profile(path: Path) -> ACTProfile:
    return ACTProfile.model_validate_json(path.read_text())


@dataclass(frozen=True)
class MotorObservation:
    state: NDArray[np.float32]
    images: dict[str, NDArray[np.uint8]]
    captured_at: float
    camera_times: dict[str, float]
    axes: tuple[str, ...]
    clock_id: str = "unix"
    base_stopped: bool = True
    elevator_stopped: bool = True
    other_arm_stopped: bool = True
    initial_region_confirmed: bool = True
    provenance: str = "artificial_pipeline_only"

    def validate(self, profile: ACTProfile, *, now: float) -> None:
        if self.provenance != profile.provenance or self.clock_id != profile.clock_id:
            raise ValueError("observation provenance/clock mismatch")
        if self.axes != profile.axes or self.state.shape != (len(profile.axes),):
            raise ValueError("state dimension/order mismatch")
        if self.state.dtype != np.float32 or not np.isfinite(self.state).all():
            raise ValueError("state must be finite float32")
        if np.any(self.state < profile.lower) or np.any(self.state > profile.upper):
            raise ValueError("state outside declared bounds")
        if set(self.images) != set(profile.cameras) or set(self.camera_times) != set(
            profile.cameras
        ):
            raise ValueError("required camera missing or unexpected")
        times = [self.captured_at, *self.camera_times.values()]
        if not np.isfinite([now, *times]).all() or any(
            not 0 <= now - t <= profile.max_age_s for t in times
        ):
            raise ValueError("stale/future observation")
        if max(times) - min(times) > profile.max_skew_s:
            raise ValueError("unsynchronized cameras/state")
        for image in self.images.values():
            if image.dtype != np.uint8 or image.shape != (*profile.image_hw, 3):
                raise ValueError("camera image shape/type mismatch")
        if not all(
            (
                self.base_stopped,
                self.elevator_stopped,
                self.other_arm_stopped,
                self.initial_region_confirmed,
            )
        ):
            raise ValueError("stationary base/elevator/other arm and work region required")

    def payload(self) -> dict[str, Any]:
        return {
            "state": self.state.tolist(),
            "images": {k: v.tolist() for k, v in self.images.items()},
        }


def validate_chunk(profile: ACTProfile, chunk: NDArray[np.float32]) -> None:
    if chunk.shape != (profile.chunk_size, len(profile.axes)) or not np.isfinite(chunk).all():
        raise ValueError("invalid action chunk dimensions or nonfinite values")
    if np.any(chunk < profile.lower) or np.any(chunk > profile.upper):
        raise ValueError("action outside bounds")


def synthetic_observation(
    profile: ACTProfile, frame: int, episode: int, *, at: float
) -> MotorObservation:
    phase = frame / 12 + episode * 0.05
    state = np.array([0.07 * np.sin(phase + i) for i in range(len(profile.axes))], dtype=np.float32)
    y, x = np.indices(profile.image_hw)
    images = {
        name: np.stack(
            [(x + frame * 3 + k * 25) % 256, (y + episode * 7) % 256, (x + y + k * 30) % 256],
            axis=-1,
        ).astype(np.uint8)
        for k, name in enumerate(profile.cameras)
    }
    return MotorObservation(state, images, at, {name: at for name in profile.cameras}, profile.axes)
