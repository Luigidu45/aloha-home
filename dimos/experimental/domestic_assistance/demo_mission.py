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

"""Run an explicitly artificial mission and audit its journal, without robot/model services."""

import argparse
import hashlib
from pathlib import Path
from typing import cast
from uuid import uuid4

from dimos.experimental.domestic_assistance.contracts import (
    ComponentManifest,
    ExperimentManifest,
    Limits,
    Mission,
    Origin,
    RunMetadata,
    Scenario,
)
from dimos.experimental.domestic_assistance.rollouts import EpisodeJournal, audit_episode
from dimos.experimental.domestic_assistance.runner import MissionRunner
from dimos.experimental.domestic_assistance.supervisor import ScriptedSupervisor
from dimos.experimental.domestic_assistance.testing_executor import (
    DeterministicExecutor,
    Fault,
    ManualClock,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task",
        choices=("recoger_ropa", "preparar_bandeja"),
        default="recoger_ropa",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fault", choices=("failed", "unknown", "timeout", "cancel_unconfirmed"))
    parser.add_argument("--code-version", default="development-uncommitted")
    args = parser.parse_args()
    config_directory = Path(__file__).parent / "configs"
    mission_path = config_directory / f"{args.task}.json"
    scenario_path = config_directory / f"{args.task}_nominal.json"
    mission = Mission.model_validate_json(mission_path.read_text())
    scenario = Scenario.model_validate_json(scenario_path.read_text())
    scenario.validate_mission(mission)
    clock = ManualClock()
    locations = {item.object_id: item.zone for item in scenario.initial_placements}
    relations = {
        item.object_id: {(item.target_id, item.relation)}
        for item in scenario.initial_placements
        if item.target_id is not None and item.relation is not None
    }
    executor = DeterministicExecutor(
        clock,
        locations,
        scenario.initial_robot_zone,
        faults={3: cast("Fault", args.fault)} if args.fault else None,
        relations=relations,
        bimanual_objects={
            goal.object_id for goal in mission.goals if goal.manipulation_mode == "bimanual"
        },
    )
    component = ComponentManifest(name="domestic-assistance", version=args.code_version)
    metadata = RunMetadata(
        episode_id=f"test-{uuid4().hex}",
        scenario_id=scenario.scenario_id,
        session_id="demo",
        split_group=scenario.split_group,
        seed=0,
        origin=Origin.TEST,
        manifest=ExperimentManifest(
            experiment_id="domestic-assistance-software-test",
            method="software-test",
            code=component,
            supervisor=ComponentManifest(name="scripted-supervisor", version="scripted-v2"),
            executor=ComponentManifest(name="deterministic-executor", version="deterministic-v2"),
            verifier=ComponentManifest(name="observed-facts", version="observed-facts-v2"),
            mission_config_sha256=hashlib.sha256(mission_path.read_bytes()).hexdigest(),
            scenario_config_sha256=hashlib.sha256(scenario_path.read_bytes()).hexdigest(),
            code_dirty=args.code_version == "development-uncommitted",
        ),
    )
    with EpisodeJournal(args.output, metadata.episode_id) as journal:
        runner = MissionRunner(
            mission,
            metadata,
            executor,
            executor,
            ScriptedSupervisor(scenario.nominal_actions),
            journal,
            limits=Limits(skill_timeout_s=1, cancellation_timeout_s=1),
            clock=clock,
        )
        while runner.summary is None:
            runner.tick()
            clock.advance(0.1)
        print(runner.summary.model_dump_json(indent=2))
    report = audit_episode(journal.path)
    print(f"Journal: {journal.path}")
    print(report.model_dump_json(indent=2))
    if not report.complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
