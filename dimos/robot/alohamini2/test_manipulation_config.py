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

from __future__ import annotations

from dataclasses import dataclass

import pytest

from dimos.manipulation.planning.factory import create_kinematics, create_world
from dimos.manipulation.planning.spec.enums import IKStatus, ObstacleType, PlanningStatus
from dimos.manipulation.planning.spec.models import Obstacle
import dimos.manipulation.planning.utils.mesh_utils as mesh_utils
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.sensor_msgs.JointState import JointState
from dimos.robot.alohamini2.manipulation_config import (
    SO101_MOUNT_X,
    SO101_MOUNT_Y,
    SO101_MOUNT_Z,
    so101_model_config,
)
from dimos.robot.alohamini2.so101_home import SO101_ARM_JOINTS


@dataclass
class _PlanningScene:
    world: object
    robots: list[tuple[str, object]]


@pytest.fixture
def planning_scene(tmp_path, monkeypatch) -> _PlanningScene:
    monkeypatch.setattr(mesh_utils, "_CACHE_DIR", tmp_path / "urdf-cache")
    world = create_world("roboplan")
    robots = []
    for side in ("left", "right"):
        config = so101_model_config(side)
        robot_id = world.add_robot(config)
        robots.append((robot_id, config))
    world.finalize()
    for robot_id, config in robots:
        world.sync_from_joint_state(
            robot_id,
            JointState(name=config.joint_names, position=config.home_joints),
        )
    world.add_obstacle(
        Obstacle(
            name="alohamini2_central_tower",
            obstacle_type=ObstacleType.BOX,
            pose=PoseStamped(frame_id="world", position=[-0.04, 0.0, 0.63]),
            dimensions=(0.14, 0.24, 0.76),
        )
    )
    return _PlanningScene(world=world, robots=robots)


def test_dual_so101_configs_match_mounts_coordinator_and_saved_home() -> None:
    left = so101_model_config("left")
    right = so101_model_config("right")

    assert left.model_path.exists()
    assert left.joint_names == list(SO101_ARM_JOINTS)
    assert left.base_pose.position.to_list() == pytest.approx(
        [SO101_MOUNT_X, SO101_MOUNT_Y, SO101_MOUNT_Z]
    )
    assert right.base_pose.position.to_list() == pytest.approx(
        [SO101_MOUNT_X, -SO101_MOUNT_Y, SO101_MOUNT_Z]
    )
    assert left.get_coordinator_joint_names() == [f"left_arm/{name}" for name in SO101_ARM_JOINTS]
    assert right.get_coordinator_joint_names() == [f"right_arm/{name}" for name in SO101_ARM_JOINTS]
    assert left.coordinator_task_name == "traj_left_arm"
    assert right.coordinator_task_name == "traj_right_arm"
    assert left.home_joints == right.home_joints


def test_saved_dual_arm_home_is_collision_free_and_mirrored(
    planning_scene: _PlanningScene,
) -> None:
    world = planning_scene.world
    context = world.get_live_context()
    poses = []
    for robot_id, _config in planning_scene.robots:
        assert world.is_collision_free(context, robot_id)
        poses.append(world.get_ee_pose(context, robot_id))

    assert poses[0].x == pytest.approx(poses[1].x, abs=1e-9)
    # The calibrated source URDF carries a ~9 nm shoulder-frame Y offset;
    # after the folded chain rotations it produces a ~20 um mirror residual.
    assert poses[0].y == pytest.approx(-poses[1].y, abs=3e-5)
    assert poses[0].z == pytest.approx(poses[1].z, abs=1e-9)
    assert [poses[0].x, poses[0].y, poses[0].z] == pytest.approx(
        [0.2412, 0.18726, 0.6001], abs=5e-4
    )


def test_pink_ik_and_roboplan_plan_small_cartesian_motion(
    planning_scene: _PlanningScene,
) -> None:
    world = planning_scene.world
    robot_id, config = planning_scene.robots[0]
    seed = JointState(name=config.joint_names, position=config.home_joints)
    current = world.get_ee_pose(world.get_live_context(), robot_id)
    target = PoseStamped(
        frame_id="world",
        position=[current.x + 0.01, current.y, current.z],
        orientation=current.orientation,
    )

    ik_result = create_kinematics("pink").solve(
        world,
        robot_id,
        target,
        seed=seed,
        check_collision=True,
        max_attempts=3,
    )

    assert ik_result.status is IKStatus.SUCCESS
    assert ik_result.joint_state is not None
    assert ik_result.position_error < 0.001
    plan = world.plan_joint_path(
        world,
        robot_id,
        seed,
        ik_result.joint_state,
        timeout=3.0,
    )
    assert plan.status is PlanningStatus.SUCCESS
    assert len(plan.path) >= 2
