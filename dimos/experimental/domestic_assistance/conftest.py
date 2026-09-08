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

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import pytest

from dimos.experimental.domestic_assistance.contracts import (
    Action,
    ComponentManifest,
    ExperimentManifest,
    Goal,
    Limits,
    Mission,
    MissionTarget,
    Origin,
    PlacementTarget,
    RunMetadata,
    SpatialRelation,
)
from dimos.experimental.domestic_assistance.rollouts import EpisodeJournal
from dimos.experimental.domestic_assistance.runner import MissionRunner
from dimos.experimental.domestic_assistance.supervisor import ScriptedSupervisor, transfer_script
from dimos.experimental.domestic_assistance.testing_executor import (
    DeterministicExecutor,
    Fault,
    ManualClock,
)


@dataclass
class Rig:
    runner: MissionRunner
    executor: DeterministicExecutor
    clock: ManualClock
    journal: EpisodeJournal
    mission: Mission
    supervisor: ScriptedSupervisor

    def finish(self) -> None:
        for _ in range(100):
            self.runner.tick()
            self.clock.advance(0.1)
            if self.runner.summary is not None:
                return
        raise AssertionError("mission did not terminate")


@pytest.fixture
def make_rig(tmp_path: Path) -> Iterator[Callable[..., Rig]]:
    with ExitStack() as stack:

        def create(
            faults: dict[int, Fault] | None = None,
            actions: tuple[Action, ...] | None = None,
            limits: Limits | None = None,
        ) -> Rig:
            clock = ManualClock()
            mission = Mission(
                task_id="reading",
                instruction="Bring book",
                zones=("shelf", "desk"),
                targets=(MissionTarget(target_id="book_spot", kind="surface"),),
                goals=(
                    Goal(
                        object_id="book",
                        destination=PlacementTarget(
                            zone="desk",
                            target_id="book_spot",
                            relation=SpatialRelation.ON,
                        ),
                    ),
                ),
            )
            locations = {"book": "shelf"}
            executor = DeterministicExecutor(clock, locations, "shelf", faults)
            metadata = RunMetadata(
                episode_id=f"episode-{len(tuple(tmp_path.glob('*.jsonl')))}",
                scenario_id="nominal",
                session_id="session",
                split_group="group",
                seed=1,
                origin=Origin.TEST,
                manifest=ExperimentManifest(
                    experiment_id="domestic-test",
                    method="software-test",
                    code=ComponentManifest(name="code", version="test"),
                    supervisor=ComponentManifest(name="supervisor", version="scripted-v2"),
                    executor=ComponentManifest(name="executor", version="deterministic-v2"),
                    verifier=ComponentManifest(name="verifier", version="observed-facts-v2"),
                ),
            )
            journal = stack.enter_context(EpisodeJournal(tmp_path, metadata.episode_id))
            supervisor = ScriptedSupervisor(
                actions if actions is not None else transfer_script(mission, locations),
            )
            runner = MissionRunner(
                mission,
                metadata,
                executor,
                executor,
                supervisor,
                journal,
                limits=limits
                if limits is not None
                else Limits(
                    skill_timeout_s=0.5,
                    cancellation_timeout_s=0.5,
                ),
                clock=clock,
            )
            return Rig(runner, executor, clock, journal, mission, supervisor)

        yield create
