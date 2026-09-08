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

import json
from pathlib import Path

import pytest

from dimos.experimental.domestic_assistance.configuration import load_config_bundle
from dimos.experimental.domestic_assistance.contracts import Action, SpatialRelation

CONFIG_DIRECTORY = Path(__file__).parent / "configs"


@pytest.mark.parametrize("task_id", ["recoger_ropa", "preparar_bandeja"])
def test_nominal_scenario_matches_mission_and_decision_limit(task_id):
    bundle = load_config_bundle(
        CONFIG_DIRECTORY / f"{task_id}.json",
        CONFIG_DIRECTORY / f"{task_id}_nominal.json",
    )
    assert bundle.config_schema_version == 1
    assert len(bundle.scenario.nominal_actions) <= 20
    assert len(bundle.mission_config_sha256) == 64
    assert len(bundle.scenario_config_sha256) == 64


def test_clothes_require_containment_in_the_basket():
    mission = load_config_bundle(
        CONFIG_DIRECTORY / "recoger_ropa.json",
        CONFIG_DIRECTORY / "recoger_ropa_nominal.json",
    ).mission
    assert {goal.destination.target_id for goal in mission.goals} == {"cesto_ropa"}
    assert {goal.destination.relation for goal in mission.goals} == {SpatialRelation.IN}


def test_tray_mission_requires_nested_support_relations():
    mission = load_config_bundle(
        CONFIG_DIRECTORY / "preparar_bandeja.json",
        CONFIG_DIRECTORY / "preparar_bandeja_nominal.json",
    ).mission
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


def test_loader_rejects_a_configuration_without_an_explicit_version(tmp_path):
    mission_payload = json.loads((CONFIG_DIRECTORY / "recoger_ropa.json").read_text())
    mission_payload.pop("config_schema_version")
    mission_path = tmp_path / "mission.json"
    mission_path.write_text(json.dumps(mission_payload), encoding="utf-8")

    with pytest.raises(ValueError, match="config_schema_version"):
        load_config_bundle(mission_path, CONFIG_DIRECTORY / "recoger_ropa_nominal.json")


def test_scenario_rejects_duplicate_or_missing_initial_objects():
    bundle = load_config_bundle(
        CONFIG_DIRECTORY / "recoger_ropa.json",
        CONFIG_DIRECTORY / "recoger_ropa_nominal.json",
    )
    placements = bundle.scenario.initial_placements
    duplicate = bundle.scenario.model_copy(
        update={"initial_placements": (*placements, placements[0])}
    )
    missing = bundle.scenario.model_copy(update={"initial_placements": placements[:-1]})

    with pytest.raises(ValueError, match="unique"):
        duplicate.validate_mission(bundle.mission)
    with pytest.raises(ValueError, match="every mission object"):
        missing.validate_mission(bundle.mission)


def test_scenario_rejects_a_nominal_place_without_a_pick():
    bundle = load_config_bundle(
        CONFIG_DIRECTORY / "recoger_ropa.json",
        CONFIG_DIRECTORY / "recoger_ropa_nominal.json",
    )
    incoherent = bundle.scenario.model_copy(
        update={
            "nominal_actions": (
                Action(skill="NAVIGATE", zone="zona_cesto"),
                Action(
                    skill="PLACE",
                    object_id="camiseta",
                    zone="zona_cesto",
                    target_id="cesto_ropa",
                    relation=SpatialRelation.IN,
                ),
            )
        }
    )

    with pytest.raises(ValueError, match="object is not held"):
        incoherent.validate_mission(bundle.mission)
