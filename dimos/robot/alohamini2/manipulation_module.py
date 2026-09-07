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

"""Base-relative Cartesian manipulation for the dual SO101 AlohaMini2."""

from __future__ import annotations

from dimos.agents.annotation import skill
from dimos.agents.skill_result import SkillResult
from dimos.manipulation.manipulation_module import ManipulationModule
from dimos.manipulation.skill_errors import ManipulationSkillError
from dimos.msgs.geometry_msgs.Pose import Pose
from dimos.robot.alohamini2.so101_home import SO101_SIDES


class AlohaMini2ManipulationModule(ManipulationModule):
    """Dual-arm planner whose Cartesian reference frame is ``base_link``."""

    def _initialize_planning(self) -> None:
        super()._initialize_planning()
        if self.world_monitor is None:
            return

        # Lightweight envelope for the central lift column. The arm mounting
        # plates are deliberately outside this box so the saved home remains a
        # valid collision-free configuration.
        obstacle_id = self.add_obstacle(
            name="alohamini2_central_tower",
            pose=Pose(-0.04, 0.0, 0.63),
            shape="box",
            dimensions=[0.14, 0.24, 0.76],
        )
        if not obstacle_id:
            raise RuntimeError("Failed to add the AlohaMini2 tower collision envelope")

    @staticmethod
    def _robot_name(side: str) -> str:
        normalized = side.strip().lower()
        if normalized not in SO101_SIDES:
            raise ValueError("side must be 'left' or 'right'")
        return f"{normalized}_arm"

    @skill
    def get_so101_cartesian_state(self, side: str) -> SkillResult[ManipulationSkillError]:
        """Get SO101 joints and end-effector pose relative to AlohaMini2 base_link.

        Args:
            side: Arm to query: left or right.
        """
        return self.get_robot_state(self._robot_name(side))

    @skill
    def move_so101_to_pose(
        self,
        side: str,
        x: float,
        y: float,
        z: float,
        roll: float | None = None,
        pitch: float | None = None,
        yaw: float | None = None,
    ) -> SkillResult[ManipulationSkillError]:
        """Plan and execute a collision-checked Cartesian SO101 motion.

        Coordinates are meters in the mobile robot's base_link frame: +X is
        forward, +Y is left, and +Z is up. Omit all orientation values to keep
        the current gripper orientation.

        Args:
            side: Arm to move: left or right.
            x: Target X position relative to base_link in meters.
            y: Target Y position relative to base_link in meters.
            z: Target Z position relative to base_link in meters.
            roll: Optional target roll in radians.
            pitch: Optional target pitch in radians.
            yaw: Optional target yaw in radians.
        """
        return self.move_to_pose(
            x=x,
            y=y,
            z=z,
            roll=roll,
            pitch=pitch,
            yaw=yaw,
            robot_name=self._robot_name(side),
        )

    @skill
    def go_so101_planned_home(self, side: str) -> SkillResult[ManipulationSkillError]:
        """Plan and execute a collision-checked move to the saved SO101 home.

        Args:
            side: Arm to move: left or right.
        """
        robot_name = self._robot_name(side)
        robot = self._get_robot(robot_name)
        if robot is None:
            return SkillResult.fail("ROBOT_NOT_FOUND", "Robot not found")
        _, _, config, _ = robot
        if config.home_joints is None:
            return SkillResult.fail("NOT_CONFIGURED", "No home pose configured")
        joints = ",".join(str(value) for value in config.home_joints)
        return self.move_to_joints(joints, robot_name)


alohamini2_manipulation_module = AlohaMini2ManipulationModule.blueprint
