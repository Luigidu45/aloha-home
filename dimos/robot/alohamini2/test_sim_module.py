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

from collections.abc import Iterator
import math
from typing import cast

import mujoco
import numpy as np
import pytest

from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.msgs.geometry_msgs.Vector3 import Vector3
from dimos.robot.alohamini2.config import (
    ALOHA_MINI2_NAV_CAMERAS,
    ALOHA_MINI2_NAV_MJCF,
    ALOHA_MINI2_OFFICE_LITE_MJCF,
    ALOHA_MINI2_OFFICE_SCENE_MJCF,
    ALOHA_MINI2_OFFICE_SPAWN_XY,
    ALOHA_MINI2_RGB_CAMERAS,
    ALOHA_MINI2_SO101_HOME,
)
from dimos.robot.alohamini2.sim_module import (
    HolonomicCommandBuffer,
    PlanarVelocity,
    apply_planar_velocity,
    body_velocity_to_world,
    yaw_from_wxyz,
)
from dimos.robot.alohamini2.so101_home import apply_so101_home_pose, load_so101_home_pose
from dimos.simulation.engines.mujoco_engine import (
    MujocoEngine,
    RaycastLidarConfig,
    RaycastLidarFrame,
)
from dimos.simulation.engines.mujoco_sim_module import add_legacy_office_person
from dimos.utils.testing.waiting import wait_until


def _composed_model(
    scene_path: str,
    *,
    include_person: bool = False,
) -> mujoco.MjModel:
    scene = mujoco.MjSpec.from_file(scene_path)
    if include_person:
        add_legacy_office_person(scene)
    robot = mujoco.MjSpec.from_file(str(ALOHA_MINI2_NAV_MJCF))
    apply_so101_home_pose(robot, load_so101_home_pose(ALOHA_MINI2_SO101_HOME))
    scene.option.timestep = robot.option.timestep
    frame = scene.worldbody.add_frame(pos=[*ALOHA_MINI2_OFFICE_SPAWN_XY, 0.0])
    scene.attach(robot, frame=frame)
    return scene.compile()


def _twist(vx: float, vy: float, wz: float) -> Twist:
    return Twist(
        linear=Vector3(vx, vy, 0.0),
        angular=Vector3(0.0, 0.0, wz),
    )


@pytest.fixture
def raycast_engine() -> Iterator[MujocoEngine]:
    raycast_lidars = [
        RaycastLidarConfig(
            name=name,
            width=20,
            height=10,
            fps=20.0,
            min_range=0.1,
            max_range=6.0,
            max_height=1.8,
            geom_groups=(0, 1, 2, 3, 4, 5),
            robot_exclusion_radius=0.55,
        )
        for name in ALOHA_MINI2_NAV_CAMERAS
    ]
    engine = MujocoEngine(
        config_path=ALOHA_MINI2_NAV_MJCF,
        headless=True,
        model=_composed_model(str(ALOHA_MINI2_OFFICE_LITE_MJCF)),
        raycast_lidars=raycast_lidars,
    )
    assert engine.connect()
    try:
        yield engine
    finally:
        engine.disconnect()


def test_command_buffer_limits_vector_speed_and_yaw_rate() -> None:
    commands = HolonomicCommandBuffer(
        timeout=0.25,
        max_linear_speed=0.5,
        max_yaw_rate=1.2,
    )

    command = commands.update(_twist(0.6, 0.8, 2.0), now=10.0)

    assert command == PlanarVelocity(vx=0.3, vy=0.4, wz=1.2)


def test_command_buffer_watchdog_stops_at_deadline() -> None:
    commands = HolonomicCommandBuffer(
        timeout=0.25,
        max_linear_speed=0.5,
        max_yaw_rate=1.2,
    )
    expected = commands.update(_twist(0.2, -0.1, 0.3), now=5.0)

    assert commands.sample(now=5.249) == expected
    assert commands.sample(now=5.25) == PlanarVelocity()


def test_body_velocity_rotates_with_robot_heading() -> None:
    world = body_velocity_to_world(PlanarVelocity(vx=0.4), yaw=math.pi / 2)

    assert world.vx == pytest.approx(0.0, abs=1e-12)
    assert world.vy == pytest.approx(0.4)
    assert world.wz == 0.0


@pytest.mark.mujoco
def test_navigation_mjcf_has_required_visuals_freejoint_sensors_and_cameras() -> None:
    model = mujoco.MjModel.from_xml_path(str(ALOHA_MINI2_NAV_MJCF))

    root_joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "root")
    camera_names = tuple(
        mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_CAMERA, index) for index in range(model.ncam)
    )
    sensor_names = {
        mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_SENSOR, index)
        for index in range(model.nsensor)
    }

    assert int(model.jnt_type[root_joint_id]) == int(mujoco.mjtJoint.mjJNT_FREE)
    assert set(camera_names) == {
        *ALOHA_MINI2_NAV_CAMERAS,
        *ALOHA_MINI2_RGB_CAMERAS,
    }
    assert sensor_names == {"imu_gyro", "imu_accel"}
    cad_geom_ids = [
        index
        for index in range(model.ngeom)
        if (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, index) or "").startswith("cad_")
    ]

    assert model.nmesh == 22
    assert int(model.mesh_facenum.sum()) < 150_000
    assert len(cad_geom_ids) == 44
    assert all(int(model.geom_contype[index]) == 0 for index in cad_geom_ids)
    assert all(int(model.geom_conaffinity[index]) == 0 for index in cad_geom_ids)
    wrist_gripper_geom_ids = {
        mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, f"cad_{side}_so101_{part}_visual")
        for side in ("left", "right")
        for part in ("gripper_servo", "wrist_roll_follower", "moving_jaw")
    }
    assert all(
        int(model.geom_group[index]) == (1 if index in wrist_gripper_geom_ids else 2)
        for index in cad_geom_ids
    )
    assert model.nu == 0
    assert float(model.body_mass.sum()) == pytest.approx(18.0)
    for side, expected_x in (("left", 0.18726), ("right", -0.18726)):
        body_id = mujoco.mj_name2id(
            model,
            mujoco.mjtObj.mjOBJ_BODY,
            f"cad_{side}_so101_base_body",
        )
        assert tuple(model.body_pos[body_id]) == pytest.approx((expected_x, -0.0599, 0.4775))
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cad_left_base_body") == -1
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cad_right_base_body") == -1


@pytest.mark.mujoco
@pytest.mark.parametrize("side", ["left", "right"])
def test_wrist_camera_centers_its_corresponding_gripper(side: str) -> None:
    model = mujoco.MjModel.from_xml_path(str(ALOHA_MINI2_NAV_MJCF))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    camera_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, f"{side}_camera")
    camera_body_id = mujoco.mj_name2id(
        model,
        mujoco.mjtObj.mjOBJ_BODY,
        f"cad_{side}_camera_body",
    )
    gripper_centers = []

    for part in ("gripper_servo", "wrist_roll_follower", "moving_jaw"):
        geom_id = mujoco.mj_name2id(
            model,
            mujoco.mjtObj.mjOBJ_GEOM,
            f"cad_{side}_so101_{part}_visual",
        )
        mesh_id = int(model.geom_dataid[geom_id])
        vertex_start = int(model.mesh_vertadr[mesh_id])
        vertex_count = int(model.mesh_vertnum[mesh_id])
        vertices = model.mesh_vert[vertex_start : vertex_start + vertex_count]
        rotation = data.geom_xmat[geom_id].reshape(3, 3)
        world_vertices = vertices @ rotation.T + data.geom_xpos[geom_id]
        gripper_centers.append((world_vertices.min(axis=0) + world_vertices.max(axis=0)) / 2)

    gripper_center = np.mean(gripper_centers, axis=0)
    camera_rotation = data.cam_xmat[camera_id].reshape(3, 3)
    center_in_camera = camera_rotation.T @ (gripper_center - data.cam_xpos[camera_id])

    assert float(np.linalg.norm(center_in_camera[:2])) < 2e-3
    assert center_in_camera[2] < -0.07
    assert tuple(model.body_pos[camera_body_id]) == pytest.approx(
        (0.0, 0.055 if side == "left" else -0.055, 0.04)
    )
    assert tuple(model.cam_pos[camera_id]) == pytest.approx((0.0, 0.0, 0.022))
    assert float(model.cam_fovy[camera_id]) == pytest.approx(90.0)


@pytest.mark.mujoco
def test_so101_arms_are_complete_symmetric_and_in_folded_home_pose() -> None:
    model = mujoco.MjModel.from_xml_path(str(ALOHA_MINI2_NAV_MJCF))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    base_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "base_link")
    gripper_positions = {}
    expected_body_parts = {
        "base",
        "shoulder",
        "upper_arm",
        "lower_arm",
        "wrist",
        "gripper",
        "moving_jaw",
    }

    for side in ("left", "right"):
        body_ids = {
            mujoco.mj_name2id(
                model,
                mujoco.mjtObj.mjOBJ_BODY,
                f"cad_{side}_so101_{part}_body",
            )
            for part in expected_body_parts
        }
        arm_geom_ids = {
            index
            for index in range(model.ngeom)
            if (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, index) or "").startswith(
                f"cad_{side}_so101_"
            )
        }
        gripper_id = mujoco.mj_name2id(
            model,
            mujoco.mjtObj.mjOBJ_BODY,
            f"cad_{side}_so101_gripper_body",
        )

        assert -1 not in body_ids
        assert len(arm_geom_ids) == 17
        gripper_positions[side] = data.xpos[gripper_id] - data.xpos[base_id]

    assert gripper_positions["left"] == pytest.approx((0.1166, 0.1871, 0.6076), abs=1e-3)
    assert gripper_positions["right"] == pytest.approx((0.1166, -0.1874, 0.6076), abs=1e-3)


@pytest.mark.mujoco
def test_office_scene_matches_go2_environment_person_and_spawn_xy() -> None:
    model = _composed_model(str(ALOHA_MINI2_OFFICE_SCENE_MJCF), include_person=True)
    data = mujoco.MjData(model)

    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "floor") >= 0
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "geom_Room_001_Walls") >= 0
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "person") >= 0
    assert model.nmocap == 1
    assert tuple(data.qpos[:2]) == pytest.approx(ALOHA_MINI2_OFFICE_SPAWN_XY)
    assert float(data.qpos[2]) == pytest.approx(0.064)


@pytest.mark.mujoco
def test_lite_scene_preserves_navigation_obstacles_with_few_geometries() -> None:
    model = _composed_model(str(ALOHA_MINI2_OFFICE_LITE_MJCF))
    data = mujoco.MjData(model)

    assert model.ngeom < 80
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "floor") >= 0
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "front_desk_top") >= 0
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "meeting_table_top") >= 0
    assert tuple(data.qpos[:2]) == pytest.approx(ALOHA_MINI2_OFFICE_SPAWN_XY)
    assert model.nmocap == 0
    assert float(model.stat.extent * model.vis.map.znear) < 0.005


@pytest.mark.mujoco
def test_all_navigation_cameras_produce_world_raycast_points(
    raycast_engine: MujocoEngine,
) -> None:
    wait_until(
        lambda: all(
            raycast_engine.read_raycast_lidar(name) is not None for name in ALOHA_MINI2_NAV_CAMERAS
        ),
        timeout=2.0,
    )

    frames = [raycast_engine.read_raycast_lidar(name) for name in ALOHA_MINI2_NAV_CAMERAS]

    assert all(frame is not None and len(frame.points) > 0 for frame in frames)
    points = np.vstack([cast("RaycastLidarFrame", frame).points for frame in frames])
    assert len(points) > 400
    assert float(np.max(np.abs(points[:, :2]))) >= 4.8


@pytest.mark.mujoco
@pytest.mark.parametrize(
    ("command", "expected_xy"),
    [
        (PlanarVelocity(vx=0.3), (0.3, 0.0)),
        (PlanarVelocity(vy=0.3), (0.0, 0.3)),
    ],
)
def test_planar_driver_moves_without_tipping(
    command: PlanarVelocity,
    expected_xy: tuple[float, float],
) -> None:
    engine = MujocoEngine(config_path=ALOHA_MINI2_NAV_MJCF, headless=True)

    for _ in range(200):
        apply_planar_velocity(engine, command)
        mujoco.mj_step(engine.model, engine.data)

    np.testing.assert_allclose(engine.data.qpos[:2], expected_xy, atol=0.01)
    np.testing.assert_allclose(engine.data.qpos[4:6], [0.0, 0.0], atol=1e-3)
    assert float(engine.data.qpos[2]) == pytest.approx(0.064, abs=1e-3)


@pytest.mark.mujoco
def test_planar_driver_rotates_without_tipping() -> None:
    engine = MujocoEngine(config_path=ALOHA_MINI2_NAV_MJCF, headless=True)

    for _ in range(200):
        apply_planar_velocity(engine, PlanarVelocity(wz=0.5))
        mujoco.mj_step(engine.model, engine.data)

    quaternion = tuple(float(value) for value in engine.data.qpos[3:7])
    assert yaw_from_wxyz(cast("tuple[float, float, float, float]", quaternion)) == pytest.approx(
        0.5,
        abs=0.03,
    )
    np.testing.assert_allclose(engine.data.qpos[4:6], [0.0, 0.0], atol=1e-3)
