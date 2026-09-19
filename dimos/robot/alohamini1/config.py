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

"""AlohaMini1 navigation geometry and virtual sensor configuration.

The supplied URDF has zero limits for all arm/elevator joints. Navigation uses
its CAD zero pose; these envelopes and cameras are simulation assumptions.
"""

from pathlib import Path

from dimos.utils.data import LfsPath

ASSETS = Path(__file__).resolve().parent / "assets"
ALOHA_MINI1_NAV_MJCF = ASSETS / "robot.xml"
ALOHA_MINI1_HOUSE_MJCF = ASSETS / "alohamini1_house.xml"
ALOHA_MINI1_OFFICE_LITE_MJCF = ASSETS / "alohamini1_office_lite.xml"
ALOHA_MINI1_OFFICE_SCENE_MJCF = LfsPath("mujoco_sim") / "scene_office1.xml"
ALOHA_MINI1_NAV_CAMERAS = ("nav_front", "nav_left", "nav_back", "nav_right")
ALOHA_MINI1_RGB_CAMERAS = (
    "front_camera",
    "chest_camera",
    "left_camera",
    "right_camera",
)
ALOHA_MINI1_NAV_WIDTH_M = 0.50
ALOHA_MINI1_NAV_ROTATION_DIAMETER_M = 0.80
ALOHA_MINI1_NAV_HEIGHT_M = 1.15
ALOHA_MINI1_NAV_SAFE_RADIUS_M = 0.45
ALOHA_MINI1_NAV_VOXEL_SIZE_M = 0.05
ALOHA_MINI1_NAV_MAX_STEP_HEIGHT_M = 0.10
ALOHA_MINI1_BASE_HEIGHT_M = 0.005

ALOHA_MINI1_OFFICE_SPAWN_XY = (-1.0, 1.0)
