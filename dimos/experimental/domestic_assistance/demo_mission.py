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
from pathlib import Path
from typing import cast
from uuid import uuid4

from dimos.experimental.domestic_assistance.contracts import Limits, Mission, Origin, RunMetadata
from dimos.experimental.domestic_assistance.rollouts import EpisodeJournal, audit_episode
from dimos.experimental.domestic_assistance.runner import MissionRunner
from dimos.experimental.domestic_assistance.supervisor import ScriptedSupervisor, transfer_script
from dimos.experimental.domestic_assistance.testing_executor import (
    DeterministicExecutor,
    Fault,
    ManualClock,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("lectura", "ordenar_sala"), default="lectura")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--objects", type=int, choices=(1, 2), default=1)
    parser.add_argument("--fault", choices=("failed", "unknown", "timeout", "cancel_unconfirmed"))
    parser.add_argument("--code-version", default="development-uncommitted")
    args = parser.parse_args()
    mission = Mission.model_validate_json(
        (Path(__file__).parent / "configs" / f"{args.task}.json").read_text()
    )
    mission = mission.model_copy(update={"goals": mission.goals[: args.objects]})
    clock = ManualClock()
    locations = {
        goal.object_id: mission.zones[index % 2] for index, goal in enumerate(mission.goals)
    }
    executor = DeterministicExecutor(
        clock,
        locations,
        mission.zones[0],
        faults={3: cast("Fault", args.fault)} if args.fault else None,
    )
    metadata = RunMetadata(
        episode_id=f"test-{uuid4().hex}",
        scenario_id=f"{args.task}-{args.objects}-objects-artificial",
        session_id="demo",
        split_group="software-test-only",
        seed=0,
        origin=Origin.TEST,
        code_version=args.code_version,
        supervisor_version="scripted-v1",
        executor_version="deterministic-v1",
        verifier_version="observed-facts-v1",
    )
    with EpisodeJournal(args.output, metadata.episode_id) as journal:
        runner = MissionRunner(
            mission,
            metadata,
            executor,
            executor,
            ScriptedSupervisor(transfer_script(mission, locations)),
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
