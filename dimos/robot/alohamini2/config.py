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

"""Physical and navigation constants for the reduced AlohaMini2 model."""

from pathlib import Path

from dimos.utils.data import get_data

ALOHA_MINI2_NAV_MJCF: Path = Path(__file__).resolve().parent / "assets" / "alohamini2_nav.xml"
ALOHA_MINI2_SO101_HOME: Path = (
    Path(__file__).resolve().parent / "assets" / "alohamini2_so101_home.json"
)
ALOHA_MINI2_COLOR_SCHEME: Path = (
    Path(__file__).resolve().parent / "assets" / "alohamini2_print_colors.json"
)
ALOHA_MINI2_OFFICE_LITE_MJCF: Path = (
    Path(__file__).resolve().parent / "assets" / "alohamini2_office_lite.xml"
)
ALOHA_MINI2_OFFICE_SCENE_MJCF: Path = get_data("mujoco_sim") / "scene_office1.xml"
ALOHA_MINI2_NAV_CAMERAS = (
    "nav_front",
    "nav_left",
    "nav_back",
    "nav_right",
)
ALOHA_MINI2_RGB_CAMERAS = (
    "front_camera",
    "back_camera",
    "chest_camera",
    "left_camera",
    "right_camera",
)

# Same default X/Y used by ``dimos --simulation run unitree-go2``.
ALOHA_MINI2_OFFICE_SPAWN_XY = (-1.0, 1.0)

# Conservative dimensions from the source URDF with both arms at zero pose.
ALOHA_MINI2_NAV_WIDTH_M = 0.58
ALOHA_MINI2_NAV_ROTATION_DIAMETER_M = 0.95
ALOHA_MINI2_NAV_HEIGHT_M = 1.2
ALOHA_MINI2_NAV_SAFE_RADIUS_M = 0.55
ALOHA_MINI2_NAV_VOXEL_SIZE_M = 0.05
ALOHA_MINI2_NAV_MAX_STEP_HEIGHT_M = 0.10
