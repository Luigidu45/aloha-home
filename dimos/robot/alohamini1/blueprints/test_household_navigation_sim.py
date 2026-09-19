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

import mujoco
import pytest

from dimos.experimental.household_assistant.spatial import load_spatial
from dimos.experimental.household_assistant.spatial_module import HouseholdSpatialModule
from dimos.navigation.replanning_a_star.module import ReplanningAStarPlanner
from dimos.robot.alohamini1.blueprints.household_navigation_sim import household_navigation_sim
from dimos.robot.alohamini1.config import ALOHA_MINI1_NAV_MJCF
from dimos.robot.alohamini1.sim_module import AlohaMini1SimModule


def test_household_blueprint_uses_registered_stations_and_existing_navigation():
    atoms = {atom.module: atom for atom in household_navigation_sim.active_blueprints}
    assert HouseholdSpatialModule in atoms
    assert ReplanningAStarPlanner in atoms
    sim = atoms[AlohaMini1SimModule].kwargs
    assert sim["scene_xml"].name == "household_navigation.xml"
    assert sim["robot_mjcf"] == ALOHA_MINI1_NAV_MJCF
    assert sim["dof"] == 0
    assert sim["spawn_xy"] == (-2.5, -1.0)
    assert {station.place_id for station in load_spatial().stations} == {
        "mesa_sala",
        "mesa_dormitorio",
        "suelo_sala",
    }


@pytest.mark.mujoco
@pytest.mark.parametrize("blocked", [False, True])
def test_household_scene_compiles_with_passage_and_task_surfaces(blocked):
    name = "household_navigation_blocked.xml" if blocked else "household_navigation.xml"
    scene = mujoco.MjSpec.from_file(str(ALOHA_MINI1_NAV_MJCF.parent / name))
    robot = mujoco.MjSpec.from_file(str(ALOHA_MINI1_NAV_MJCF))
    scene.attach(robot, frame=scene.worldbody.add_frame(pos=[-2.5, -1.0, 0.0]))
    model = scene.compile()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    assert model.geom("pickup_top").pos[2] + model.geom("pickup_top").size[2] == pytest.approx(0.75)
    assert model.geom("delivery_top").pos[2] + model.geom("delivery_top").size[2] == pytest.approx(
        0.75
    )
    gate_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "blocked_passage")
    assert (gate_id >= 0) == blocked
    assert model.cam("/front_camera").id >= 0
    assert model.cam("/nav_front").id >= 0
