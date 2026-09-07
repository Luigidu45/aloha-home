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

"""Planning-model configuration for the dual SO101 AlohaMini2 arms."""

from __future__ import annotations

from pathlib import Path

from dimos.manipulation.planning.groups.models import PlanningGroupDefinition
from dimos.manipulation.planning.spec.config import RobotModelConfig
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Quaternion import Quaternion
from dimos.msgs.geometry_msgs.Vector3 import Vector3
from dimos.robot.alohamini2.config import ALOHA_MINI2_SO101_HOME
from dimos.robot.alohamini2.so101_home import (
    SO101_ARM_JOINTS,
    SO101_JOINT_RANGES,
    SO101_SIDES,
    load_so101_home_pose,
)

SO101_PLANNING_URDF = Path(__file__).parent / "assets" / "so101_planning.urdf"

# The detailed MuJoCo model is nested below base_link -> cad_visual_frame ->
# cad_vertical_link_body. Combining those transforms places both arm bases in
# the DimOS convention (+X forward, +Y left) with identity orientation.
SO101_MOUNT_X = 0.0599
SO101_MOUNT_Y = 0.18726
SO101_MOUNT_Z = 0.096196 + 0.4775

# Adjacent links are disabled automatically by the RoboPlan model builder. The
# folded SO101 home also puts these non-adjacent conservative primitives close
# enough to touch, so exclude only the pairs belonging to the same mechanism.
SO101_COLLISION_EXCLUSIONS = [
    ("base_link", "upper_arm_link"),
    ("shoulder_link", "lower_arm_link"),
    ("shoulder_link", "wrist_link"),
    ("upper_arm_link", "wrist_link"),
    ("lower_arm_link", "gripper_link"),
]


def so101_model_config(side: str) -> RobotModelConfig:
    """Build one base-relative SO101 planning configuration.

    Cartesian targets passed to ManipulationModule are expressed in the
    AlohaMini2 ``base_link`` frame. ``left_arm`` and ``right_arm`` are separate
    robots in one composite RoboPlan scene, so inter-arm collision checks are
    available in addition to each arm's self-collision checks.
    """
    if side not in SO101_SIDES:
        raise ValueError(f"Unknown SO101 side: {side!r}")

    robot_name = f"{side}_arm"
    joints = list(SO101_ARM_JOINTS)
    pose = load_so101_home_pose(ALOHA_MINI2_SO101_HOME)[side]
    lower = [SO101_JOINT_RANGES[name][0] for name in joints]
    upper = [SO101_JOINT_RANGES[name][1] for name in joints]
    return RobotModelConfig(
        name=robot_name,
        model_path=SO101_PLANNING_URDF,
        base_pose=PoseStamped(
            frame_id="world",
            position=Vector3(
                SO101_MOUNT_X,
                SO101_MOUNT_Y if side == "left" else -SO101_MOUNT_Y,
                SO101_MOUNT_Z,
            ),
            orientation=Quaternion(0.0, 0.0, 0.0, 1.0),
        ),
        joint_names=joints,
        base_link="base_link",
        planning_groups=[
            PlanningGroupDefinition(
                name="manipulator",
                joint_names=tuple(joints),
                base_link="base_link",
                tip_link="gripper_frame_link",
            )
        ],
        joint_limits_lower=lower,
        joint_limits_upper=upper,
        velocity_limits=[0.8] * len(joints),
        collision_exclusion_pairs=SO101_COLLISION_EXCLUSIONS,
        max_velocity=0.65,
        max_acceleration=1.2,
        joint_name_mapping={f"{robot_name}/{name}": name for name in joints},
        coordinator_task_name=f"traj_{robot_name}",
        gripper_hardware_id=robot_name,
        home_joints=[pose[name] for name in joints],
        pre_grasp_offset=0.08,
    )
