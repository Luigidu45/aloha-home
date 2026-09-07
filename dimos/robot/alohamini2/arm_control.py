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

"""Joint-space control helpers and skills for the dual SO101 AlohaMini2."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from pydantic import Field

from dimos.agents.annotation import skill
from dimos.control.components import HardwareComponent, HardwareType
from dimos.control.coordinator import ControlCoordinator
from dimos.core.core import rpc
from dimos.core.module import Module, ModuleConfig
from dimos.core.rpc_client import RPCClient
from dimos.msgs.trajectory_msgs.JointTrajectory import JointTrajectory
from dimos.msgs.trajectory_msgs.TrajectoryPoint import TrajectoryPoint
from dimos.robot.alohamini2.config import (
    ALOHA_MINI2_NAV_MJCF,
    ALOHA_MINI2_SO101_HOME,
)
from dimos.robot.alohamini2.so101_home import (
    SO101_ARM_JOINTS,
    SO101_JOINT_RANGES,
    SO101_JOINTS_PER_SIDE,
    SO101_SIDES,
    load_so101_home_pose,
)


def so101_hardware(side: str) -> HardwareComponent:
    """Describe one SO101 view into the shared AlohaMini2 MuJoCo model."""
    if side not in SO101_SIDES:
        raise ValueError(f"Unknown SO101 side: {side!r}")
    side_index = SO101_SIDES.index(side)
    offset = side_index * SO101_JOINTS_PER_SIDE
    gripper_limits = SO101_JOINT_RANGES["gripper"]
    return HardwareComponent(
        hardware_id=f"{side}_arm",
        hardware_type=HardwareType.MANIPULATOR,
        joints=[f"{side}_arm/{name}" for name in SO101_ARM_JOINTS],
        gripper_joints=[f"{side}_arm/gripper"],
        adapter_type="sim_mujoco",
        address=str(ALOHA_MINI2_NAV_MJCF),
        adapter_kwargs={
            "joint_offset": offset,
            "gripper_index": offset + len(SO101_ARM_JOINTS),
        },
        gripper_open_position=gripper_limits[1],
        gripper_closed_position=gripper_limits[0],
    )


def make_so101_trajectory(
    side: str,
    current_positions: dict[str, float],
    target_positions: dict[str, float],
    duration: float,
) -> JointTrajectory:
    """Build a two-point trajectory in coordinator joint-name order."""
    if side not in SO101_SIDES:
        raise ValueError(f"side must be one of {SO101_SIDES}, got {side!r}")
    if not math.isfinite(duration) or duration <= 0.0:
        raise ValueError("duration must be a positive finite number")

    names = [f"{side}_arm/{name}" for name in SO101_ARM_JOINTS]
    targets: list[float] = []
    starts: list[float] = []
    for local_name, coordinator_name in zip(SO101_ARM_JOINTS, names, strict=True):
        if coordinator_name not in current_positions:
            raise ValueError(f"Missing current position for {coordinator_name}")
        if local_name not in target_positions:
            raise ValueError(f"Missing target position for {local_name}")
        target = float(target_positions[local_name])
        lower, upper = SO101_JOINT_RANGES[local_name]
        if not math.isfinite(target) or target < lower or target > upper:
            raise ValueError(f"{local_name}={target} is outside [{lower}, {upper}] radians")
        starts.append(float(current_positions[coordinator_name]))
        targets.append(target)

    zeros = [0.0] * len(names)
    return JointTrajectory(
        joint_names=names,
        points=[
            TrajectoryPoint(time_from_start=0.0, positions=starts, velocities=zeros),
            TrajectoryPoint(time_from_start=duration, positions=targets, velocities=zeros),
        ],
    )


class AlohaMini2ArmControlConfig(ModuleConfig):
    home_pose: Path = Field(default=ALOHA_MINI2_SO101_HOME)


class AlohaMini2ArmControl(Module):
    """User-facing joint control for both simulated SO101 arms."""

    config: AlohaMini2ArmControlConfig

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._coordinator: RPCClient | None = None

    @rpc
    def start(self) -> None:
        super().start()
        self._coordinator = RPCClient(None, ControlCoordinator)

    def _client(self) -> RPCClient:
        if self._coordinator is None:
            raise RuntimeError("SO101 arm control is not started")
        return self._coordinator

    @rpc
    def get_so101_joint_positions(self) -> dict[str, float]:
        """Return the current joints of both SO101 arms and grippers."""
        positions = self._client().get_joint_positions()
        return dict(positions or {})

    def _selected_sides(self, side: str) -> tuple[str, ...]:
        normalized = side.strip().lower()
        if normalized == "both":
            return SO101_SIDES
        if normalized not in SO101_SIDES:
            raise ValueError("side must be 'left', 'right', or 'both'")
        return (normalized,)

    def _execute_targets(
        self,
        side: str,
        targets_by_side: dict[str, dict[str, float]],
        duration: float,
    ) -> bool:
        client = self._client()
        current = dict(client.get_joint_positions() or {})
        accepted = True
        for selected_side in self._selected_sides(side):
            trajectory = make_so101_trajectory(
                selected_side,
                current,
                targets_by_side[selected_side],
                duration,
            )
            result = client.task_invoke(
                f"traj_{selected_side}_arm",
                "execute",
                {"trajectory": trajectory},
            )
            accepted = bool(result) and accepted
        return accepted

    @skill
    def move_so101_joints(
        self,
        side: str,
        shoulder_pan: float,
        shoulder_lift: float,
        elbow_flex: float,
        wrist_flex: float,
        wrist_roll: float,
        duration: float = 2.0,
    ) -> str:
        """Move one or both SO101 arms to a joint configuration in radians.

        Args:
            side: Arm to move: left, right, or both.
            shoulder_pan: Horizontal shoulder angle in radians.
            shoulder_lift: Vertical shoulder angle in radians.
            elbow_flex: Elbow angle in radians.
            wrist_flex: Wrist pitch angle in radians.
            wrist_roll: Wrist roll angle in radians.
            duration: Motion duration in seconds.
        """
        target = {
            "shoulder_pan": shoulder_pan,
            "shoulder_lift": shoulder_lift,
            "elbow_flex": elbow_flex,
            "wrist_flex": wrist_flex,
            "wrist_roll": wrist_roll,
        }
        targets = {selected_side: dict(target) for selected_side in SO101_SIDES}
        if not self._execute_targets(side, targets, duration):
            return f"No se pudo iniciar el movimiento del SO101 {side}."
        return f"Movimiento del SO101 {side} iniciado; duración {duration:.2f} s."

    @skill
    def go_so101_home(self, side: str = "both", duration: float = 2.0) -> str:
        """Move one or both SO101 arms to the saved home pose.

        Args:
            side: Arm to move: left, right, or both.
            duration: Motion duration in seconds.
        """
        pose = load_so101_home_pose(self.config.home_pose)
        if not self._execute_targets(side, pose, duration):
            return f"No se pudo iniciar el home del SO101 {side}."
        return f"SO101 {side} moviéndose al home guardado."

    @skill
    def set_so101_gripper(self, side: str, opening: float) -> str:
        """Set the normalized opening of one or both SO101 grippers.

        Args:
            side: Gripper to move: left, right, or both.
            opening: Normalized opening, where 0 is closed and 1 is open.
        """
        if not math.isfinite(opening) or not 0.0 <= opening <= 1.0:
            raise ValueError("opening must be between 0 and 1")
        lower, upper = SO101_JOINT_RANGES["gripper"]
        physical_position = lower + opening * (upper - lower)
        client = self._client()
        results = [
            bool(client.set_gripper_position(f"{selected_side}_arm", physical_position))
            for selected_side in self._selected_sides(side)
        ]
        if not all(results):
            return f"No se pudo mover el gripper SO101 {side}."
        return f"Gripper SO101 {side} ajustado a {opening:.2f}."

    @skill
    def stop_so101_arms(self) -> str:
        """Cancel active trajectories and hold both SO101 arms in place."""
        client = self._client()
        for side in SO101_SIDES:
            client.task_invoke(f"traj_{side}_arm", "cancel", {})
        client.set_estop(True)
        return "Brazos SO101 detenidos; E-STOP de manipulación activado."

    @rpc
    def clear_so101_estop(self) -> bool:
        """Clear the manipulation-only E-STOP after checking the workspace."""
        return bool(self._client().set_estop(False))


aloha_mini2_arm_control = AlohaMini2ArmControl.blueprint
