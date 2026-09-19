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

from typing import Any

import mujoco
from rerun.blueprint import Blueprint as RerunBlueprint

from dimos.robot.alohamini1.blueprints.alohamini1_nav_sim import (
    ALOHA_MINI1_RERUN_CONFIG,
    _alohamini1_navigation,
    _alohamini1_navigation_full,
    _alohamini1_rerun_blueprint,
    _alohamini1_visualization,
)
from dimos.robot.alohamini1.config import (
    ALOHA_MINI1_HOUSE_MJCF,
    ALOHA_MINI1_NAV_MJCF,
    ALOHA_MINI1_OFFICE_SCENE_MJCF,
    ALOHA_MINI1_RGB_CAMERAS,
)
from dimos.robot.alohamini1.sim_module import AlohaMini1SimModule
from dimos.visualization.rerun.constants import ViewerBackend


def _module_names(viewer_backend: ViewerBackend) -> set[str]:
    blueprint = _alohamini1_visualization(viewer_backend)
    return {atom.module.__name__ for atom in blueprint.active_blueprints}


def _sim_kwargs(blueprint: Any) -> dict[str, Any]:
    return next(
        atom.kwargs for atom in blueprint.active_blueprints if atom.module is AlohaMini1SimModule
    )


def test_rerun_backend_includes_dimos_viewer_bridge_and_navigation_topics() -> None:
    module_names = _module_names("rerun")

    assert {
        "RerunBridgeModule",
        "RerunWebSocketServer",
        "WebsocketVisModule",
    } <= module_names
    assert {
        "world/pointcloud",
        "world/global_map",
        "world/global_costmap",
        "world/path",
        "world/goal_request",
    } <= ALOHA_MINI1_RERUN_CONFIG["visual_override"].keys()
    assert {
        f"world/{camera_name}_image" for camera_name in ALOHA_MINI1_RGB_CAMERAS
    } <= ALOHA_MINI1_RERUN_CONFIG["max_hz"].keys()


def test_none_backend_keeps_navigation_headless() -> None:
    module_names = _module_names("none")

    assert "RerunBridgeModule" not in module_names
    assert "RerunWebSocketServer" not in module_names
    assert "WebsocketVisModule" in module_names


def test_navigation_viewer_layout_builds_with_installed_rerun_sdk() -> None:
    layout = _alohamini1_rerun_blueprint()

    assert isinstance(layout, RerunBlueprint)


def test_default_navigation_profile_uses_lite_scene_and_bounded_sensor_work() -> None:
    config = _sim_kwargs(_alohamini1_navigation)

    assert config["scene_xml"] == ALOHA_MINI1_HOUSE_MJCF
    assert config["include_legacy_office_person"] is False
    assert (config["width"], config["height"], config["fps"]) == (256, 144, 2)
    assert config["camera_geom_groups"] is None
    assert config["dof"] == 0
    assert config["camera_near_clip_fraction"] == 0.0002
    assert config["camera_geom_group_overrides"] == {}
    assert config["camera_max_geom"] == 256
    assert config["max_camera_renders_per_step"] == 1
    assert (
        config["mujoco_lidar_raycast_width"],
        config["mujoco_lidar_raycast_height"],
        config["pointcloud_fps"],
    ) == (40, 12, 4.0)


def test_full_navigation_profile_retains_original_office_quality() -> None:
    config = _sim_kwargs(_alohamini1_navigation_full)

    assert config["scene_xml"] == ALOHA_MINI1_OFFICE_SCENE_MJCF
    assert config["include_legacy_office_person"] is True
    assert (config["width"], config["height"], config["fps"]) == (640, 360, 8)
    assert config["camera_geom_groups"] is None


def test_house_scene_contains_required_rooms_and_fixtures() -> None:
    scene = mujoco.MjSpec.from_file(str(ALOHA_MINI1_HOUSE_MJCF))
    robot = mujoco.MjSpec.from_file(str(ALOHA_MINI1_NAV_MJCF))
    scene.option.timestep = robot.option.timestep
    frame = scene.worldbody.add_frame(pos=[-1.0, 1.0, 0.0])
    scene.attach(robot, frame=frame)
    model = scene.compile()

    expected_bodies = [
        "sofa",
        "coffee_table",
        "tv_unit",
        "refrigerator",
        "kitchen_counter",
        "dining_table",
        "bed_master",
        "toilet",
        "shower",
        "bathroom_vanity",
        "bed_single",
        "study_desk",
    ]
    for body_name in expected_bodies:
        assert mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name) >= 0

    assert model.ngeom < 150
