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
from dimos.robot.alohamini1.config import (
    ALOHA_MINI1_NAV_CAMERAS,
    ALOHA_MINI1_NAV_MJCF,
    ALOHA_MINI1_OFFICE_LITE_MJCF,
    ALOHA_MINI1_OFFICE_SCENE_MJCF,
    ALOHA_MINI1_OFFICE_SPAWN_XY,
)
from dimos.robot.alohamini1.sim_module import (
    AlohaMini1SimModule,
    HolonomicCommandBuffer,
    PlanarVelocity,
    apply_planar_velocity,
    body_velocity_to_world,
    yaw_from_wxyz,
)
from dimos.simulation.engines.mujoco_engine import (
    CameraFrame,
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
    robot = mujoco.MjSpec.from_file(str(ALOHA_MINI1_NAV_MJCF))
    scene.option.timestep = robot.option.timestep
    frame = scene.worldbody.add_frame(pos=[*ALOHA_MINI1_OFFICE_SPAWN_XY, 0.0])
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
        for name in ALOHA_MINI1_NAV_CAMERAS
    ]
    engine = MujocoEngine(
        config_path=ALOHA_MINI1_NAV_MJCF,
        headless=True,
        model=_composed_model(str(ALOHA_MINI1_OFFICE_LITE_MJCF)),
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
def test_office_scene_matches_go2_environment_person_and_spawn_xy() -> None:
    model = _composed_model(str(ALOHA_MINI1_OFFICE_SCENE_MJCF), include_person=True)
    data = mujoco.MjData(model)

    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "floor") >= 0
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "geom_Room_001_Walls") >= 0
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "person") >= 0
    assert model.nmocap == 1
    assert tuple(data.qpos[:2]) == pytest.approx(ALOHA_MINI1_OFFICE_SPAWN_XY)
    assert float(data.qpos[2]) == pytest.approx(0.005)


@pytest.mark.mujoco
def test_lite_scene_preserves_navigation_obstacles_with_few_geometries() -> None:
    model = _composed_model(str(ALOHA_MINI1_OFFICE_LITE_MJCF))
    data = mujoco.MjData(model)

    assert model.ngeom < 80
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "floor") >= 0
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "front_desk_top") >= 0
    assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "meeting_table_top") >= 0
    assert tuple(data.qpos[:2]) == pytest.approx(ALOHA_MINI1_OFFICE_SPAWN_XY)
    assert model.nmocap == 0
    assert float(model.stat.extent * model.vis.map.znear) < 0.005


@pytest.mark.mujoco
def test_all_navigation_cameras_produce_world_raycast_points(
    raycast_engine: MujocoEngine,
) -> None:
    wait_until(
        lambda: all(
            raycast_engine.read_raycast_lidar(name) is not None for name in ALOHA_MINI1_NAV_CAMERAS
        ),
        timeout=2.0,
    )

    frames = [raycast_engine.read_raycast_lidar(name) for name in ALOHA_MINI1_NAV_CAMERAS]

    assert all(frame is not None and len(frame.points) > 0 for frame in frames)
    points = np.vstack([cast("RaycastLidarFrame", frame).points for frame in frames])
    assert len(points) > 400
    assert float(np.max(np.abs(points[:, :2]))) >= 4.8


@pytest.fixture
def standalone_engine():
    engine = MujocoEngine(config_path=ALOHA_MINI1_NAV_MJCF, headless=True)
    try:
        yield engine
    finally:
        engine.disconnect()


@pytest.mark.mujoco
@pytest.mark.parametrize(
    ("command", "expected_xy"),
    [
        (PlanarVelocity(vx=0.3), (0.3, 0.0)),
        (PlanarVelocity(vy=0.3), (0.0, 0.3)),
    ],
)
def test_planar_driver_moves_without_tipping(
    standalone_engine: MujocoEngine,
    command: PlanarVelocity,
    expected_xy: tuple[float, float],
) -> None:
    engine = standalone_engine

    for _ in range(200):
        apply_planar_velocity(engine, command)
        mujoco.mj_step(engine.model, engine.data)

    np.testing.assert_allclose(engine.data.qpos[:2], expected_xy, atol=0.01)
    np.testing.assert_allclose(engine.data.qpos[4:6], [0.0, 0.0], atol=1e-3)
    assert float(engine.data.qpos[2]) == pytest.approx(0.005, abs=1e-3)


@pytest.mark.mujoco
def test_planar_driver_rotates_without_tipping(standalone_engine: MujocoEngine) -> None:
    engine = standalone_engine

    for _ in range(200):
        apply_planar_velocity(engine, PlanarVelocity(wz=0.5))
        mujoco.mj_step(engine.model, engine.data)

    quaternion = tuple(float(value) for value in engine.data.qpos[3:7])
    assert yaw_from_wxyz(cast("tuple[float, float, float, float]", quaternion)) == pytest.approx(
        0.5,
        abs=0.03,
    )
    np.testing.assert_allclose(engine.data.qpos[4:6], [0.0, 0.0], atol=1e-3)


@pytest.fixture
def camera_publisher(mocker):
    module = AlohaMini1SimModule(camera_name="front_camera", additional_camera_names=[])
    frame = CameraFrame(
        rgb=np.ones((2, 2, 3), dtype=np.uint8),
        depth=np.zeros((2, 2), dtype=np.float32),
        cam_pos=np.zeros(3),
        cam_mat=np.eye(3),
        fovy=69.0,
        timestamp=10.0,
    )
    engine = mocker.Mock(spec=MujocoEngine)
    engine.read_camera.return_value = frame
    engine.connected = True
    mocker.patch.object(module, "_engine", engine)
    mocker.patch.object(module, "_publish_tf")
    yield module
    module.stop()


def test_camera_publication_preserves_capture_timestamp(camera_publisher, mocker):
    published = mocker.patch.object(
        camera_publisher.front_camera_image,
        "publish",
        side_effect=lambda _: camera_publisher._stop_event.set(),
    )
    camera_publisher._publish_loop()
    image = published.call_args.args[0]
    assert image.ts == 10.0
    assert image.frame_id == "front_camera_color_optical_frame"
    np.testing.assert_array_equal(image.data, np.ones((2, 2, 3), dtype=np.uint8))
