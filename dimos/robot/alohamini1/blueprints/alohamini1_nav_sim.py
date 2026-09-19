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

"""AlohaMini1 holonomic navigation in the reduced MuJoCo scene."""

from pathlib import Path
from typing import Any

from dimos.core.coordination.blueprints import Blueprint, autoconnect
from dimos.core.global_config import global_config
from dimos.core.transport import JpegLcmTransport
from dimos.mapping.costmapper import CostMapper
from dimos.mapping.pointclouds.occupancy import HeightCostConfig
from dimos.mapping.voxels import VoxelGridMapper
from dimos.msgs.sensor_msgs.Image import Image
from dimos.navigation.movement_manager.movement_manager import MovementManager
from dimos.navigation.replanning_a_star.module import ReplanningAStarPlanner
from dimos.robot.alohamini1.config import (
    ALOHA_MINI1_BASE_HEIGHT_M,
    ALOHA_MINI1_HOUSE_MJCF,
    ALOHA_MINI1_NAV_CAMERAS,
    ALOHA_MINI1_NAV_HEIGHT_M,
    ALOHA_MINI1_NAV_MAX_STEP_HEIGHT_M,
    ALOHA_MINI1_NAV_MJCF,
    ALOHA_MINI1_NAV_ROTATION_DIAMETER_M,
    ALOHA_MINI1_NAV_SAFE_RADIUS_M,
    ALOHA_MINI1_NAV_VOXEL_SIZE_M,
    ALOHA_MINI1_NAV_WIDTH_M,
    ALOHA_MINI1_OFFICE_SCENE_MJCF,
    ALOHA_MINI1_RGB_CAMERAS,
)
from dimos.robot.alohamini1.sim_module import AlohaMini1SimModule
from dimos.visualization.rerun.constants import ViewerBackend
from dimos.visualization.vis_module import vis_module


def _convert_pointcloud(pointcloud: Any) -> Any:
    return pointcloud.to_rerun(
        voxel_size=ALOHA_MINI1_NAV_VOXEL_SIZE_M,
        mode="spheres",
        bottom_cutoff=0.0,
    )


def _convert_costmap(costmap: Any) -> Any:
    return costmap.to_rerun(
        colormap="Accent",
        z_offset=0.015,
        opacity=0.35,
        background="#25263f",
    )


def _convert_path(path: Any) -> Any:
    if not path.poses:
        return None
    return path.to_rerun(color=(0, 255, 128), z_offset=0.08, radii=0.04)


def _convert_goal(goal: Any) -> Any:
    return goal.to_rerun_arrow(length=0.4)


def _convert_front_camera_info(camera_info: Any) -> Any:
    return camera_info.to_rerun(
        image_topic="/world/front_camera_image",
        optical_frame="front_camera_color_optical_frame",
    )


def _static_robot_body(rr: Any) -> Any:
    return rr.Boxes3D(
        centers=[[0.0, 0.0, ALOHA_MINI1_NAV_HEIGHT_M / 2]],
        half_sizes=[
            [
                0.30,
                ALOHA_MINI1_NAV_WIDTH_M / 2,
                ALOHA_MINI1_NAV_HEIGHT_M / 2,
            ]
        ],
        colors=[(0, 255, 127)],
    )


def _alohamini1_rerun_blueprint() -> Any:
    """Four explicitly virtual camera feeds beside the 3D navigation view."""
    import rerun as rr
    import rerun.blueprint as rrb

    return rrb.Blueprint(
        rrb.Horizontal(
            rrb.Vertical(
                rrb.Horizontal(
                    rrb.Spatial2DView(origin="world/front_camera_image", name="Front"),
                    rrb.Spatial2DView(origin="world/chest_camera_image", name="Chest"),
                ),
                rrb.Horizontal(
                    rrb.Spatial2DView(origin="world/left_camera_image", name="Left wrist"),
                    rrb.Spatial2DView(origin="world/right_camera_image", name="Right wrist"),
                ),
            ),
            rrb.Spatial3DView(
                origin="world",
                name="Talos Navigation",
                background=rrb.Background(kind="SolidColor", color=[0, 0, 0]),
                line_grid=rrb.LineGrid3D(
                    plane=rr.components.Plane3D.XY.with_distance(0.5),
                ),
                overrides={
                    "world/pointcloud": rrb.EntityBehavior(visible=False),
                },
            ),
            column_shares=[1, 2],
        ),
        rrb.TimePanel(state="collapsed"),
    )


ALOHA_MINI1_RERUN_CONFIG: dict[str, Any] = {
    "blueprint": _alohamini1_rerun_blueprint,
    "visual_override": {
        "world/pointcloud": _convert_pointcloud,
        "world/global_map": _convert_pointcloud,
        "world/global_costmap": _convert_costmap,
        "world/navigation_costmap": _convert_costmap,
        "world/path": _convert_path,
        "world/goal_request": _convert_goal,
        "world/camera_info": _convert_front_camera_info,
    },
    "max_hz": {
        "world/odom": 20,
        "world/pointcloud": 3,
        "world/global_map": 2,
        "world/global_costmap": 2,
        "world/navigation_costmap": 2,
        "world/path": 0,
        "world/goal_request": 0,
        **{f"world/{name}_image": 0 for name in ALOHA_MINI1_RGB_CAMERAS},
    },
    "static": {
        "world/odom/robot_body": _static_robot_body,
    },
}


def _alohamini1_visualization(viewer_backend: ViewerBackend) -> Blueprint:
    return vis_module(
        viewer_backend=viewer_backend,
        rerun_config=ALOHA_MINI1_RERUN_CONFIG,
    )


def _navigation_stack(
    *,
    scene_xml: Path,
    include_person: bool,
    camera_width: int,
    camera_height: int,
    camera_fps: int,
    camera_geom_groups: list[int] | None,
    camera_geom_group_overrides: dict[str, list[int]] | None,
    camera_max_geom: int | None,
    max_camera_renders_per_step: int | None,
    lidar_width: int,
    lidar_height: int,
    lidar_fps: float,
    spawn_xy: tuple[float, float] | None = None,
) -> Blueprint:
    return (
        autoconnect(
            AlohaMini1SimModule.blueprint(
                robot_mjcf=ALOHA_MINI1_NAV_MJCF,
                planar_base_height=ALOHA_MINI1_BASE_HEIGHT_M,
                scene_xml=scene_xml,
                include_legacy_office_person=include_person,
                spawn_xy=spawn_xy if spawn_xy is not None else global_config.mujoco_start_pos_float,
                spawn_z=0.0,
                headless=global_config.viewer == "none",
                dof=0,
                camera_name=ALOHA_MINI1_RGB_CAMERAS[0],
                additional_camera_names=list(ALOHA_MINI1_RGB_CAMERAS),
                camera_geom_groups=camera_geom_groups,
                camera_geom_group_overrides=camera_geom_group_overrides or {},
                camera_near_clip_fraction=0.0002,
                camera_max_geom=camera_max_geom,
                max_camera_renders_per_step=max_camera_renders_per_step,
                width=camera_width,
                height=camera_height,
                fps=camera_fps,
                base_frame_id="base_link",
                enable_color=False,
                enable_depth=False,
                enable_pointcloud=True,
                enable_mujoco_lidar=True,
                mujoco_lidar_camera_names=list(ALOHA_MINI1_NAV_CAMERAS),
                mujoco_lidar_raycast_width=lidar_width,
                mujoco_lidar_raycast_height=lidar_height,
                mujoco_lidar_max_range=6.0,
                mujoco_lidar_max_height=1.8,
                mujoco_lidar_robot_exclusion_radius=ALOHA_MINI1_NAV_SAFE_RADIUS_M,
                pointcloud_fps=lidar_fps,
            ),
            VoxelGridMapper.blueprint(
                voxel_size=ALOHA_MINI1_NAV_VOXEL_SIZE_M,
                device="CPU:0",
            ),
            CostMapper.blueprint(
                config=HeightCostConfig(
                    resolution=ALOHA_MINI1_NAV_VOXEL_SIZE_M,
                    can_pass_under=ALOHA_MINI1_NAV_HEIGHT_M,
                    can_climb=ALOHA_MINI1_NAV_MAX_STEP_HEIGHT_M,
                ),
                initial_safe_radius_meters=ALOHA_MINI1_NAV_SAFE_RADIUS_M,
            ),
            ReplanningAStarPlanner.blueprint(
                goal_tolerance_m=0.10,
                holonomic=True,
                robot_width=ALOHA_MINI1_NAV_WIDTH_M,
                robot_rotation_diameter=ALOHA_MINI1_NAV_ROTATION_DIAMETER_M,
            ),
            MovementManager.blueprint(),
        )
        .remappings(
            [
                (VoxelGridMapper, "lidar", "pointcloud"),
            ]
        )
        .transports(
            {
                (f"{camera_name}_image", Image): JpegLcmTransport(
                    f"/{camera_name}_image",
                    Image,
                )
                for camera_name in ALOHA_MINI1_RGB_CAMERAS
            }
        )
    )


def alohamini1_navigation_sim_stack(
    *,
    scene_xml: Path = ALOHA_MINI1_HOUSE_MJCF,
    spawn_xy: tuple[float, float] | None = None,
) -> Blueprint:
    """Compose AlohaMini1 CAD-zero navigation in a chosen scene."""
    return _navigation_stack(
        scene_xml=scene_xml,
        include_person=False,
        camera_width=256,
        camera_height=144,
        camera_fps=2,
        camera_geom_groups=None,
        camera_geom_group_overrides=None,
        camera_max_geom=256,
        max_camera_renders_per_step=1,
        lidar_width=40,
        lidar_height=12,
        lidar_fps=4.0,
        spawn_xy=spawn_xy,
    )


_alohamini1_navigation = alohamini1_navigation_sim_stack()

_alohamini1_navigation_full = _navigation_stack(
    scene_xml=ALOHA_MINI1_OFFICE_SCENE_MJCF,
    include_person=True,
    camera_width=640,
    camera_height=360,
    camera_fps=8,
    camera_geom_groups=None,
    camera_geom_group_overrides=None,
    camera_max_geom=10000,
    max_camera_renders_per_step=1,
    lidar_width=80,
    lidar_height=24,
    lidar_fps=8.0,
)

alohamini1_nav_sim = autoconnect(
    _alohamini1_visualization(global_config.viewer),
    _alohamini1_navigation,
).global_config(
    simulation="mujoco",
    robot_model="alohamini1",
    robot_width=ALOHA_MINI1_NAV_WIDTH_M,
    robot_rotation_diameter=ALOHA_MINI1_NAV_ROTATION_DIAMETER_M,
    n_workers=9,
)

alohamini1_nav_sim_full = autoconnect(
    _alohamini1_visualization(global_config.viewer),
    _alohamini1_navigation_full,
).global_config(
    simulation="mujoco",
    robot_model="alohamini1",
    robot_width=ALOHA_MINI1_NAV_WIDTH_M,
    robot_rotation_diameter=ALOHA_MINI1_NAV_ROTATION_DIAMETER_M,
    n_workers=9,
)
