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

from rerun.blueprint import Blueprint as RerunBlueprint

from dimos.robot.alohamini2.blueprints.alohamini2_nav_sim import (
    ALOHA_MINI2_RERUN_CONFIG,
    _alohamini2_manipulation,
    _alohamini2_navigation,
    _alohamini2_navigation_full,
    _alohamini2_navigation_manip,
    _alohamini2_rerun_blueprint,
    _alohamini2_visualization,
)
from dimos.robot.alohamini2.config import (
    ALOHA_MINI2_OFFICE_LITE_MJCF,
    ALOHA_MINI2_OFFICE_SCENE_MJCF,
    ALOHA_MINI2_RGB_CAMERAS,
)
from dimos.robot.alohamini2.manipulation_module import AlohaMini2ManipulationModule
from dimos.robot.alohamini2.sim_module import AlohaMini2SimModule
from dimos.visualization.rerun.constants import ViewerBackend


def _module_names(viewer_backend: ViewerBackend) -> set[str]:
    blueprint = _alohamini2_visualization(viewer_backend)
    return {atom.module.__name__ for atom in blueprint.active_blueprints}


def _sim_kwargs(blueprint: Any) -> dict[str, Any]:
    return next(
        atom.kwargs for atom in blueprint.active_blueprints if atom.module is AlohaMini2SimModule
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
    } <= ALOHA_MINI2_RERUN_CONFIG["visual_override"].keys()
    assert {
        f"world/{camera_name}_image" for camera_name in ALOHA_MINI2_RGB_CAMERAS
    } <= ALOHA_MINI2_RERUN_CONFIG["max_hz"].keys()


def test_none_backend_keeps_navigation_headless() -> None:
    module_names = _module_names("none")

    assert "RerunBridgeModule" not in module_names
    assert "RerunWebSocketServer" not in module_names
    assert "WebsocketVisModule" in module_names


def test_navigation_viewer_layout_builds_with_installed_rerun_sdk() -> None:
    layout = _alohamini2_rerun_blueprint()

    assert isinstance(layout, RerunBlueprint)


def test_default_navigation_profile_uses_lite_scene_and_bounded_sensor_work() -> None:
    config = _sim_kwargs(_alohamini2_navigation)

    assert config["scene_xml"] == ALOHA_MINI2_OFFICE_LITE_MJCF
    assert config["include_legacy_office_person"] is False
    assert (config["width"], config["height"], config["fps"]) == (256, 144, 2)
    assert config["camera_geom_groups"] == [0, 1]
    assert config["camera_near_clip_fraction"] == 0.0002
    assert config["camera_geom_group_overrides"] == {
        "left_camera": [0, 1],
        "right_camera": [0, 1],
    }
    assert config["camera_max_geom"] == 256
    assert config["max_camera_renders_per_step"] == 1
    assert (
        config["mujoco_lidar_raycast_width"],
        config["mujoco_lidar_raycast_height"],
        config["pointcloud_fps"],
    ) == (40, 12, 4.0)


def test_full_navigation_profile_retains_original_office_quality() -> None:
    config = _sim_kwargs(_alohamini2_navigation_full)

    assert config["scene_xml"] == ALOHA_MINI2_OFFICE_SCENE_MJCF
    assert config["include_legacy_office_person"] is True
    assert (config["width"], config["height"], config["fps"]) == (640, 360, 8)
    assert config["camera_geom_groups"] is None


def test_manipulation_profile_articulates_both_so101_arms() -> None:
    config = _sim_kwargs(_alohamini2_navigation_manip)

    assert config["scene_xml"] == ALOHA_MINI2_OFFICE_LITE_MJCF
    assert config["articulated_so101"] is True
    assert config["dof"] == 12


def test_manipulation_profile_includes_dual_arm_ik_and_motion_planning() -> None:
    kwargs = next(
        atom.kwargs
        for atom in _alohamini2_manipulation.active_blueprints
        if atom.module is AlohaMini2ManipulationModule
    )

    assert [robot.name for robot in kwargs["robots"]] == ["left_arm", "right_arm"]
    assert kwargs["world_backend"] == "roboplan"
    assert kwargs["planner_name"] == "roboplan"
    assert kwargs["kinematics"].backend == "pink"
