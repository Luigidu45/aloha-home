# Copyright 2026 Dimensional Inc.
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

"""F2 synthetic living room and bedroom, with observed semantic navigation."""

from dimos.core.coordination.blueprints import autoconnect
from dimos.core.transport import LCMTransport, pLCMTransport
from dimos.experimental.household_assistant.spatial import SpatialStatus
from dimos.experimental.household_assistant.spatial_module import HouseholdSpatialModule
from dimos.msgs.sensor_msgs.Image import Image
from dimos.robot.alohamini2.blueprints.alohamini2_nav_sim import alohamini2_navigation_sim_stack
from dimos.robot.alohamini2.config import (
    ALOHA_MINI2_NAV_MJCF,
    ALOHA_MINI2_NAV_ROTATION_DIAMETER_M,
    ALOHA_MINI2_NAV_WIDTH_M,
    ALOHA_MINI2_RGB_CAMERAS,
)

household_navigation_sim = (
    autoconnect(
        alohamini2_navigation_sim_stack(
            scene_xml=ALOHA_MINI2_NAV_MJCF.parent / "household_navigation.xml",
            spawn_xy=(-2.5, -1.0),
        ),
        HouseholdSpatialModule.blueprint(),
    )
    .transports(
        {
            ("spatial_status", SpatialStatus): pLCMTransport.spec("/spatial_status"),
            **{
                (f"{name}_image", Image): LCMTransport.spec(f"/{name}_image", Image)
                for name in ALOHA_MINI2_RGB_CAMERAS
            },
        }
    )
    .global_config(
        simulation="mujoco",
        robot_model="alohamini2",
        n_workers=6,
        robot_width=ALOHA_MINI2_NAV_WIDTH_M,
        robot_rotation_diameter=ALOHA_MINI2_NAV_ROTATION_DIAMETER_M,
    )
)
