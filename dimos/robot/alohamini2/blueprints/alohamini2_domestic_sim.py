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

"""Phase-2 domestic missions: physical navigation plus symbolic manipulation."""

from pathlib import Path

from dimos.core.coordination.blueprints import Blueprint, autoconnect
from dimos.experimental.domestic_assistance.simulation_module import (
    DomesticAssistanceSimulationModule,
)
from dimos.robot.alohamini2.blueprints.alohamini2_nav_sim import (
    alohamini2_navigation_sim_stack,
)
from dimos.robot.alohamini2.config import (
    ALOHA_MINI2_NAV_ROTATION_DIAMETER_M,
    ALOHA_MINI2_NAV_WIDTH_M,
)

_CONFIGS = Path(__file__).parents[3] / "experimental" / "domestic_assistance" / "configs"


def _domestic_simulation(task_id: str) -> Blueprint:
    return autoconnect(
        alohamini2_navigation_sim_stack(),
        DomesticAssistanceSimulationModule.blueprint(
            mission_path=_CONFIGS / f"{task_id}.json",
            scenario_path=_CONFIGS / f"{task_id}_nominal.json",
            zone_map_path=_CONFIGS / f"{task_id}_simulation_zones.json",
        ),
    )


alohamini2_domestic_clothes_sim = _domestic_simulation("recoger_ropa").global_config(
    simulation="mujoco",
    robot_model="alohamini2",
    robot_width=ALOHA_MINI2_NAV_WIDTH_M,
    robot_rotation_diameter=ALOHA_MINI2_NAV_ROTATION_DIAMETER_M,
    viewer="none",
    n_workers=7,
)

alohamini2_domestic_tray_sim = _domestic_simulation("preparar_bandeja").global_config(
    simulation="mujoco",
    robot_model="alohamini2",
    robot_width=ALOHA_MINI2_NAV_WIDTH_M,
    robot_rotation_diameter=ALOHA_MINI2_NAV_ROTATION_DIAMETER_M,
    viewer="none",
    n_workers=7,
)
