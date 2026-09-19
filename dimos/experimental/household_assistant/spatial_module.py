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

"""Semantic navigation RPCs with observed arrival, cancellation and fresh snapshots."""

from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field
from reactivex.disposable import Disposable

from dimos.core.core import rpc
from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In, Out
from dimos.experimental.household_assistant.configuration import load_pilot
from dimos.experimental.household_assistant.contracts import Evidence, Origin
from dimos.experimental.household_assistant.spatial import (
    SPATIAL_SIM_CONFIG,
    PoseSample,
    PoseWindow,
    Purpose,
    SpatialConfiguration,
    SpatialStatus,
    load_spatial,
    within_approach,
)
from dimos.experimental.household_assistant.visual import ObservedView, rgb_digest
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Quaternion import Quaternion
from dimos.msgs.geometry_msgs.Vector3 import Vector3
from dimos.msgs.sensor_msgs.Image import Image
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.navigation.navigation_spec import NavigationInterfaceSpec


@dataclass(frozen=True)
class SpatialSnapshot:
    """Sensor payloads only; no simulator object identities or object poses."""

    status: SpatialStatus
    image: Image
    pointcloud: PointCloud2
    evidence: tuple[Evidence, ...]


class HouseholdSpatialConfig(ModuleConfig):
    stations_path: Path = SPATIAL_SIM_CONFIG
    pilot_path: Path = SPATIAL_SIM_CONFIG.with_name("pilot.json")
    navigation_timeout_s: float = Field(default=90.0, gt=0)
    stop_timeout_s: float = Field(default=5.0, gt=0)
    pose_max_age_s: float = Field(default=1.0, gt=0)
    observation_max_age_s: float = Field(default=2.0, gt=0)
    settle_s: float = Field(default=0.5, gt=0)
    linear_stop_mps: float = Field(default=0.03, gt=0)
    angular_stop_rps: float = Field(default=0.05, gt=0)
    tick_s: float = Field(default=0.1, gt=0)


class HouseholdSpatialModule(Module):
    config: HouseholdSpatialConfig
    odom: In[PoseStamped]
    front_camera_image: In[Image]
    pointcloud: In[PointCloud2]
    spatial_status: Out[SpatialStatus]
    _navigation: NavigationInterfaceSpec

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None
        self._stations: SpatialConfiguration | None = None
        self._poses = PoseWindow(
            settle_s=self.config.settle_s,
            max_age_s=self.config.pose_max_age_s,
            linear_stop_mps=self.config.linear_stop_mps,
            angular_stop_rps=self.config.angular_stop_rps,
            frame_id="world",
        )
        self._status = SpatialStatus(ts=0.0)
        self._image: Image | None = None
        self._cloud: PointCloud2 | None = None
        self._stopping_at = 0.0
        self._stop_result: Literal["cancelled", "failed", "arrived"] = "cancelled"
        self._arrived_at = 0.0

    @rpc
    def start(self) -> None:
        stations = load_spatial(self.config.stations_path)
        pilot = load_pilot(self.config.pilot_path)
        if {item.place_id for item in stations.stations} != {item.id for item in pilot.places}:
            raise ValueError("spatial stations must match the pilot's places")
        with self._lock:
            self._stations = stations
        super().start()
        self.register_disposable(Disposable(self.odom.subscribe(self._on_pose)))
        self.register_disposable(Disposable(self.front_camera_image.subscribe(self._on_image)))
        self.register_disposable(Disposable(self.pointcloud.subscribe(self._on_cloud)))
        self._shutdown.clear()
        self._thread = threading.Thread(target=self._run, name="HouseholdSpatial", daemon=True)
        self._thread.start()

    @rpc
    def stop(self) -> None:
        if self._shutdown.is_set():
            return
        self._shutdown.set()
        try:
            with self._lock:
                self._navigation.cancel_goal()
        finally:
            if self._thread is not None and self._thread is not threading.current_thread():
                self._thread.join(timeout=self.config.stop_timeout_s)
            super().stop()

    def _on_pose(self, pose: PoseStamped) -> None:
        with self._lock:
            self._poses.add(PoseSample.from_pose(pose))

    def _on_image(self, image: Image) -> None:
        with self._lock:
            if self._image is None or image.ts > self._image.ts:
                self._image = image

    def _on_cloud(self, cloud: PointCloud2) -> None:
        with self._lock:
            if self._cloud is None or cloud.ts > self._cloud.ts:
                self._cloud = cloud

    @rpc
    def get_planner_image(self) -> tuple[Image, ObservedView] | None:
        """Current localized RGB for F5, including before the first navigation goal.

        This is camera/observer localization, never an object pose or identity.
        The planner independently requires all actuators to be observed stopped.
        """
        with self._lock:
            image = self._image
            pose = self._poses.latest
            if image is None or pose is None or abs(image.ts - pose.ts) > 0.5:
                return None
            now = time.time()
            if not 0 <= now - image.ts <= self.config.observation_max_age_s:
                return None
            view = ObservedView(
                id=f"rgb_{int(image.ts * 1e9)}",
                evidence=Evidence(
                    origin=Origin.SIMULATION,
                    source="front_camera_image",
                    reference=f"front_camera_image@{image.ts:.9f}",
                    captured_at=image.ts,
                    clock_id="unix",
                    frame_id=image.frame_id,
                ),
                rgb_sha256=rgb_digest(image),
                observer_pose=pose,
                pose_source="mujoco_ground_truth_localization",
                map_id="household_f2_sim",
                place_id=self._status.place_id if self._status.state == "arrived" else None,
            )
            return image, view

    @rpc
    def go_to(self, place_id: str, purpose: Purpose = "observe") -> SpatialStatus:
        """Request navigation to a registered base pose; does not move arms or lift."""
        if purpose not in {"observe", "manipulate"}:
            raise ValueError("unknown approach purpose")
        with self._lock:
            if self._stations is None or self._shutdown.is_set():
                raise RuntimeError("spatial adapter is not running")
            target = self._stations.approach(place_id, purpose)
            if self._status.state in {"navigating", "stopping", "stop_unconfirmed"}:
                raise RuntimeError("previous navigation has not ended with a confirmed stop")
            now = time.time()
            if not self._poses.fresh(now):
                raise RuntimeError("fresh world-frame localization required")
            self._status = SpatialStatus(
                request_id=uuid4().hex,
                place_id=place_id,
                purpose=purpose,
                state="navigating",
                ts=now,
                started_at=now,
                pose=self._poses.latest,
            )
            goal = PoseStamped(
                ts=now,
                frame_id=self._stations.frame_id,
                position=Vector3(target.x, target.y, 0.0),
                orientation=Quaternion.from_euler(Vector3(0.0, 0.0, target.yaw)),
            )
            if not self._navigation.set_goal(goal):
                self._begin_stop("failed", "planner_rejected", now)
            return self._status

    def _begin_stop(
        self, outcome: Literal["cancelled", "failed", "arrived"], reason: str, now: float
    ) -> None:
        self._navigation.cancel_goal()
        self._stopping_at = now
        self._stop_result = outcome
        self._status = self._status.model_copy(
            update={"state": "stopping", "reason": reason, "ts": now}
        )

    @rpc
    def cancel(self) -> SpatialStatus:
        """Request planner cancellation; poll until observed stop is confirmed."""
        with self._lock:
            if self._status.state in {"navigating", "stop_unconfirmed"}:
                self._begin_stop("cancelled", "cancel_requested", time.time())
            return self._status

    @rpc
    def get_status(self) -> SpatialStatus:
        with self._lock:
            return self._status

    @rpc
    def get_observation(self, place_id: str) -> SpatialSnapshot | None:
        """Return post-arrival sensor data only while still stopped at this station."""
        with self._lock:
            now = time.time()
            status, image, cloud = self._status, self._image, self._cloud
            if (
                self._stations is None
                or status.state != "arrived"
                or status.place_id != place_id
                or image is None
                or cloud is None
                or self._poses.latest is None
            ):
                return None
            target = self._stations.approach(place_id, status.purpose)
            if not within_approach(self._poses.latest, target) or not self._poses.stopped(
                now, after=self._arrived_at
            ):
                return None
            if (
                image.frame_id != "front_camera_color_optical_frame"
                or cloud.frame_id != "world"
                or any(
                    ts <= self._arrived_at or not 0 <= now - ts <= self.config.observation_max_age_s
                    for ts in (image.ts, cloud.ts)
                )
            ):
                return None
            evidence = tuple(
                Evidence(
                    origin=Origin.SIMULATION,
                    source=source,
                    reference=f"{source}@{ts:.9f}",
                    captured_at=ts,
                    clock_id="unix",
                    frame_id=frame,
                )
                for source, ts, frame in (
                    ("mujoco_ground_truth_localization", self._poses.latest.ts, "world"),
                    ("front_camera_image", image.ts, image.frame_id),
                    ("raycast_pointcloud", cloud.ts, cloud.frame_id),
                )
            )
            return SpatialSnapshot(
                status=status.model_copy(update={"pose": self._poses.latest, "ts": now}),
                image=image,
                pointcloud=cloud,
                evidence=evidence,
            )

    def _run(self) -> None:
        while not self._shutdown.wait(self.config.tick_s):
            with self._lock:
                self._tick(time.time())
                status = self._status
            self.spatial_status.publish(status)

    def _tick(self, now: float) -> None:
        status = self._status
        if status.state == "navigating":
            if not self._poses.fresh(now):
                self._begin_stop("failed", "localization_stale", now)
            elif now - status.started_at > self.config.navigation_timeout_s:
                self._begin_stop("failed", "navigation_timeout_or_blocked", now)
            elif self._navigation.is_goal_reached():
                assert self._stations is not None and self._poses.latest is not None
                target = self._stations.approach(status.place_id, status.purpose)
                if within_approach(self._poses.latest, target):
                    self._begin_stop("arrived", "arrival_pending_stop", now)
                else:
                    self._begin_stop("failed", "planner_arrived_outside_station", now)
        if self._status.state == "stopping":
            if self._poses.stopped(now, after=self._stopping_at):
                outcome = self._stop_result
                if outcome == "arrived":
                    assert self._stations is not None and self._poses.latest is not None
                    if not within_approach(
                        self._poses.latest, self._stations.approach(status.place_id, status.purpose)
                    ):
                        outcome = "failed"
                    self._arrived_at = now
                self._status = self._status.model_copy(
                    update={
                        "state": outcome,
                        "reason": "arrival_and_stop_confirmed"
                        if outcome == "arrived"
                        else self._status.reason,
                    }
                )
            elif now - self._stopping_at > self.config.stop_timeout_s:
                self._status = self._status.model_copy(
                    update={"state": "stop_unconfirmed", "reason": "stop_evidence_missing"}
                )
        self._status = self._status.model_copy(update={"ts": now, "pose": self._poses.latest})
