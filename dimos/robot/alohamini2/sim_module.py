# Copyright 2025-2026 Dimensional Inc.
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

"""Holonomic MuJoCo driver for the AlohaMini2 navigation model."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import threading
import time
from typing import Any

from pydantic import Field
from reactivex.disposable import Disposable

from dimos.core.core import rpc
from dimos.core.stream import In, Out
from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat
from dimos.robot.alohamini2.config import ALOHA_MINI2_SO101_HOME
from dimos.robot.alohamini2.so101_home import (
    apply_so101_home_pose,
    configure_articulated_so101,
    load_so101_home_pose,
    so101_home_joint_positions,
)
from dimos.simulation.engines.mujoco_engine import MujocoEngine
from dimos.simulation.engines.mujoco_sim_module import (
    MujocoSimModule,
    MujocoSimModuleConfig,
)
from dimos.utils.logging_config import setup_logger

logger = setup_logger()

DEFAULT_CMD_VEL_TIMEOUT = 0.25
DEFAULT_MAX_LINEAR_SPEED_MPS = 0.5
DEFAULT_MAX_YAW_RATE_RPS = 1.2
DEFAULT_PLANAR_BASE_HEIGHT_M = 0.064


@dataclass(frozen=True)
class PlanarVelocity:
    """Body-frame planar velocity in SI units."""

    vx: float = 0.0
    vy: float = 0.0
    wz: float = 0.0


class HolonomicCommandBuffer:
    """Thread-safe latest-command buffer with speed limits and a watchdog."""

    def __init__(
        self,
        *,
        timeout: float,
        max_linear_speed: float,
        max_yaw_rate: float,
    ) -> None:
        self._timeout = timeout
        self._max_linear_speed = max_linear_speed
        self._max_yaw_rate = max_yaw_rate
        self._lock = threading.Lock()
        self._command = PlanarVelocity()
        self._deadline = 0.0

    def update(
        self,
        twist: Twist,
        *,
        now: float,
        duration: float | None = None,
    ) -> PlanarVelocity:
        values = (twist.linear.x, twist.linear.y, twist.angular.z)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("cmd_vel must contain finite x, y, and yaw velocities")

        vx, vy = self._limit_linear(float(values[0]), float(values[1]))
        command = PlanarVelocity(
            vx=vx,
            vy=vy,
            wz=max(-self._max_yaw_rate, min(self._max_yaw_rate, float(values[2]))),
        )
        command_lifetime = duration if duration is not None and duration > 0 else self._timeout
        with self._lock:
            self._command = command
            self._deadline = now + command_lifetime
        return command

    def sample(self, *, now: float) -> PlanarVelocity:
        with self._lock:
            if now >= self._deadline:
                self._command = PlanarVelocity()
            return self._command

    def stop(self) -> None:
        with self._lock:
            self._command = PlanarVelocity()
            self._deadline = 0.0

    def _limit_linear(self, vx: float, vy: float) -> tuple[float, float]:
        speed = math.hypot(vx, vy)
        if speed <= self._max_linear_speed or speed == 0.0:
            return vx, vy
        scale = self._max_linear_speed / speed
        return vx * scale, vy * scale


def body_velocity_to_world(command: PlanarVelocity, yaw: float) -> PlanarVelocity:
    """Rotate a body-frame planar velocity into the world frame."""
    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)
    return PlanarVelocity(
        vx=cos_yaw * command.vx - sin_yaw * command.vy,
        vy=sin_yaw * command.vx + cos_yaw * command.vy,
        wz=command.wz,
    )


def yaw_from_wxyz(quaternion: tuple[float, float, float, float]) -> float:
    """Extract yaw from a MuJoCo ``(w, x, y, z)`` quaternion."""
    w, x, y, z = quaternion
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def apply_planar_velocity(
    engine: MujocoEngine,
    command: PlanarVelocity,
    *,
    base_height: float = DEFAULT_PLANAR_BASE_HEIGHT_M,
) -> None:
    """Apply a body-frame planar command to an engine's freejoint velocity."""
    qpos_adr = engine.root_qpos_adr
    qvel_adr = engine.root_qvel_adr
    if qpos_adr is None or qvel_adr is None:
        raise ValueError("Holonomic control requires a freejoint root")

    quaternion = (
        float(engine.data.qpos[qpos_adr + 3]),
        float(engine.data.qpos[qpos_adr + 4]),
        float(engine.data.qpos[qpos_adr + 5]),
        float(engine.data.qpos[qpos_adr + 6]),
    )
    yaw = yaw_from_wxyz(quaternion)
    engine.data.qpos[qpos_adr + 2] = base_height
    engine.data.qpos[qpos_adr + 3 : qpos_adr + 7] = (
        math.cos(yaw * 0.5),
        0.0,
        0.0,
        math.sin(yaw * 0.5),
    )
    engine.data.qvel[qvel_adr + 2 : qvel_adr + 5] = 0.0
    world_command = body_velocity_to_world(command, yaw)
    engine.data.qvel[qvel_adr] = world_command.vx
    engine.data.qvel[qvel_adr + 1] = world_command.vy
    engine.data.qvel[qvel_adr + 5] = world_command.wz


class AlohaMini2SimConfig(MujocoSimModuleConfig):
    cmd_vel_timeout: float = Field(default=DEFAULT_CMD_VEL_TIMEOUT, gt=0)
    max_linear_speed: float = Field(default=DEFAULT_MAX_LINEAR_SPEED_MPS, gt=0)
    max_yaw_rate: float = Field(default=DEFAULT_MAX_YAW_RATE_RPS, gt=0)
    planar_base_height: float = Field(default=DEFAULT_PLANAR_BASE_HEIGHT_M, gt=0)
    so101_home_pose: Path = ALOHA_MINI2_SO101_HOME
    articulated_so101: bool = False


class AlohaMini2SimModule(MujocoSimModule):
    """MuJoCo sensor backend with direct holonomic base velocity control."""

    config: AlohaMini2SimConfig
    cmd_vel: In[Twist]
    front_camera_image: Out[Image]
    back_camera_image: Out[Image]
    chest_camera_image: Out[Image]
    left_camera_image: Out[Image]
    right_camera_image: Out[Image]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._commands = HolonomicCommandBuffer(
            timeout=self.config.cmd_vel_timeout,
            max_linear_speed=self.config.max_linear_speed,
            max_yaw_rate=self.config.max_yaw_rate,
        )

    def _configure_robot_spec(self, spec_robot: Any) -> None:
        if self.config.articulated_so101:
            configure_articulated_so101(spec_robot)
            return
        pose = load_so101_home_pose(self.config.so101_home_pose)
        apply_so101_home_pose(spec_robot, pose)

    @rpc
    def start(self) -> None:
        if self.config.articulated_so101 and self.config.reset_joint_positions is None:
            self.config.reset_joint_positions = so101_home_joint_positions(
                load_so101_home_pose(self.config.so101_home_pose)
            )
        super().start()
        engine = self._engine
        if engine is None or engine.root_qpos_adr is None or engine.root_qvel_adr is None:
            super().stop()
            raise RuntimeError("AlohaMini2 navigation MJCF requires a freejoint root")
        try:
            self.register_disposable(Disposable(self.cmd_vel.subscribe(self._on_cmd_vel)))
        except Exception:
            super().stop()
            raise

    @rpc
    def stop(self) -> None:
        self._commands.stop()
        super().stop()

    @rpc
    def move(self, twist: Twist, duration: float = 0.0) -> bool:
        """Apply a body-frame holonomic velocity command.

        Positive ``linear.x`` moves forward, positive ``linear.y`` moves left,
        and positive ``angular.z`` turns counter-clockwise. A positive duration
        overrides the streaming-command watchdog for this call.
        """
        try:
            self._commands.update(
                twist,
                now=time.monotonic(),
                duration=duration if duration > 0 else None,
            )
        except ValueError as exc:
            logger.warning("Ignored invalid AlohaMini2 cmd_vel", error=str(exc))
            return False
        return True

    def _on_cmd_vel(self, twist: Twist) -> None:
        self.move(twist)

    def _before_sim_step(self, engine: MujocoEngine) -> None:
        super()._before_sim_step(engine)
        command = self._commands.sample(now=time.monotonic())
        apply_planar_velocity(
            engine,
            command,
            base_height=self.config.planar_base_height,
        )

    def _publish_loop(self) -> None:
        """Publish every configured Aloha RGB camera on its own typed stream."""
        engine = self._engine
        if engine is None:
            return

        camera_outputs = {
            "front_camera": self.front_camera_image,
            "back_camera": self.back_camera_image,
            "chest_camera": self.chest_camera_image,
            "left_camera": self.left_camera_image,
            "right_camera": self.right_camera_image,
        }
        configured_names = (self.config.camera_name, *self.config.additional_camera_names)
        cameras = {
            name: camera_outputs[name]
            for name in dict.fromkeys(configured_names)
            if name in camera_outputs
        }
        interval = 1.0 / self.config.fps
        last_timestamps = dict.fromkeys(cameras, 0.0)

        deadline = time.monotonic() + 30.0
        while not self._stop_event.is_set() and not engine.connected:
            if time.monotonic() > deadline:
                logger.error("AlohaMini2SimModule: timed out waiting for camera engine")
                return
            self._stop_event.wait(timeout=0.1)

        while not self._stop_event.is_set():
            published = False
            for camera_name, output in cameras.items():
                try:
                    frame = engine.read_camera(camera_name)
                except RuntimeError as exc:
                    logger.error(
                        "AlohaMini2 camera render failed; stopping publish loop",
                        camera_name=camera_name,
                        error=str(exc),
                        exc_info=True,
                    )
                    return
                if frame is None or frame.timestamp <= last_timestamps[camera_name]:
                    continue

                last_timestamps[camera_name] = frame.timestamp
                image = Image(
                    data=frame.rgb,
                    format=ImageFormat.RGB,
                    frame_id=f"{camera_name}_color_optical_frame",
                    ts=time.time(),
                )
                output.publish(image)
                if camera_name == self.config.camera_name:
                    if self.config.enable_color:
                        self.color_image.publish(image)
                    self._publish_tf(image.ts, frame)
                published = True

            if not published:
                self._stop_event.wait(timeout=interval * 0.5)
