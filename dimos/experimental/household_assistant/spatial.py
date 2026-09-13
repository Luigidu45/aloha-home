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

"""Simulation station definitions and pose-based arrival/stop checks."""

from collections import deque
from itertools import pairwise
import math
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from dimos.experimental.household_assistant.contracts import Contract, Identifier
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped

SPATIAL_SIM_CONFIG = Path(__file__).parent / "configs" / "spatial_sim.json"
Purpose = Literal["observe", "manipulate"]
SpatialState = Literal[
    "idle", "navigating", "stopping", "arrived", "cancelled", "failed", "stop_unconfirmed"
]
Positive = Annotated[float, Field(gt=0)]


class Approach(Contract):
    x: float
    y: float
    yaw: float
    lift_height_m: Annotated[float, Field(ge=0)] | None = None
    position_tolerance_m: Positive
    yaw_tolerance_rad: Annotated[float, Field(gt=0, lt=math.pi)]


class Station(Contract):
    place_id: Identifier
    observe: Approach
    manipulate: Approach
    surface_height_m: Annotated[float, Field(ge=0)]
    physical_reach_validated: Literal[False] = False


class SpatialConfiguration(Contract):
    schema_version: Literal[1]
    origin: Literal["simulation"]
    clock_id: Literal["unix"]
    frame_id: Literal["world"]
    stations: Annotated[tuple[Station, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_places(self) -> Self:
        if len({item.place_id for item in self.stations}) != len(self.stations):
            raise ValueError("duplicate spatial stations")
        return self

    def approach(self, place_id: str, purpose: Purpose) -> Approach:
        for station in self.stations:
            if station.place_id == place_id:
                return station.observe if purpose == "observe" else station.manipulate
        raise ValueError(f"unknown spatial station: {place_id}")


def load_spatial(path: Path = SPATIAL_SIM_CONFIG) -> SpatialConfiguration:
    return SpatialConfiguration.model_validate_json(path.read_text())


class PoseSample(Contract):
    ts: Annotated[float, Field(ge=0)]
    x: float
    y: float
    yaw: float
    frame_id: str

    @classmethod
    def from_pose(cls, pose: PoseStamped) -> Self:
        return cls(
            ts=pose.ts,
            x=pose.position.x,
            y=pose.position.y,
            yaw=pose.orientation.euler[2],
            frame_id=pose.frame_id,
        )


def yaw_distance(a: float, b: float) -> float:
    return abs(math.atan2(math.sin(a - b), math.cos(a - b)))


def within_approach(pose: PoseSample, target: Approach) -> bool:
    return (
        math.hypot(pose.x - target.x, pose.y - target.y) <= target.position_tolerance_m
        and yaw_distance(pose.yaw, target.yaw) <= target.yaw_tolerance_rad
    )


class PoseWindow:
    """Caller owns synchronization. Repeated timestamps never prove a stop."""

    def __init__(
        self,
        *,
        settle_s: float,
        max_age_s: float,
        linear_stop_mps: float,
        angular_stop_rps: float,
        frame_id: str,
    ) -> None:
        self._poses: deque[PoseSample] = deque(maxlen=2000)
        self._settle_s = settle_s
        self._max_age_s = max_age_s
        self._linear_stop_mps = linear_stop_mps
        self._angular_stop_rps = angular_stop_rps
        self._frame_id = frame_id

    @property
    def latest(self) -> PoseSample | None:
        return self._poses[-1] if self._poses else None

    def add(self, pose: PoseSample) -> None:
        if pose.frame_id != self._frame_id:
            return
        if self._poses and pose.ts <= self._poses[-1].ts:
            return
        self._poses.append(pose)
        while len(self._poses) > 2 and self._poses[1].ts < pose.ts - self._settle_s:
            self._poses.popleft()

    def fresh(self, now: float) -> bool:
        pose = self.latest
        return pose is not None and 0 <= now - pose.ts <= self._max_age_s

    def stopped(self, now: float, *, after: float) -> bool:
        if not self.fresh(now) or len(self._poses) < 2:
            return False
        poses = list(self._poses)
        if poses[0].ts < after or poses[-1].ts - poses[0].ts < self._settle_s:
            return False
        for first, second in pairwise(poses):
            dt = second.ts - first.ts
            if dt > self._max_age_s:
                return False
            if math.hypot(second.x - first.x, second.y - first.y) / dt > self._linear_stop_mps:
                return False
            if yaw_distance(second.yaw, first.yaw) / dt > self._angular_stop_rps:
                return False
        return True


class SpatialStatus(Contract):
    request_id: str = ""
    place_id: str = ""
    purpose: Purpose = "observe"
    state: SpatialState = "idle"
    reason: str = ""
    ts: float
    started_at: float = 0.0
    origin: Literal["simulation"] = "simulation"
    localization: Literal["mujoco_ground_truth"] = "mujoco_ground_truth"
    clock_id: Literal["unix"] = "unix"
    pose: PoseSample | None = None
