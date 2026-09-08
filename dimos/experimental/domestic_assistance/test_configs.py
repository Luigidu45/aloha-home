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

from pathlib import Path

import pytest

from dimos.experimental.domestic_assistance.contracts import Mission, Scenario, SpatialRelation

CONFIG_DIRECTORY = Path(__file__).parent / "configs"


@pytest.mark.parametrize("task_id", ["recoger_ropa", "preparar_bandeja"])
def test_nominal_scenario_matches_mission_and_decision_limit(task_id):
    mission = Mission.model_validate_json((CONFIG_DIRECTORY / f"{task_id}.json").read_text())
    scenario = Scenario.model_validate_json(
        (CONFIG_DIRECTORY / f"{task_id}_nominal.json").read_text()
    )
    scenario.validate_mission(mission)
    assert len(scenario.nominal_actions) <= 20


def test_clothes_require_containment_in_the_basket():
    mission = Mission.model_validate_json((CONFIG_DIRECTORY / "recoger_ropa.json").read_text())
    assert {goal.destination.target_id for goal in mission.goals} == {"cesto_ropa"}
    assert {goal.destination.relation for goal in mission.goals} == {SpatialRelation.IN}


def test_tray_mission_requires_nested_support_relations():
    mission = Mission.model_validate_json((CONFIG_DIRECTORY / "preparar_bandeja.json").read_text())
    destinations = {
        goal.object_id: (goal.destination.target_id, goal.destination.relation)
        for goal in mission.goals
    }
    assert destinations == {
        "vaso_1": ("bandeja", SpatialRelation.ON),
        "plato_1": ("bandeja", SpatialRelation.ON),
        "bandeja": ("superficie_cocina", SpatialRelation.ON),
    }
    assert next(
        goal for goal in mission.goals if goal.object_id == "bandeja"
    ).manipulation_mode == ("bimanual")
