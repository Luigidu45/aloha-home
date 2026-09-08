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

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from dimos.experimental.domestic_assistance.contracts import (
    ComponentManifest,
    DispatchStatus,
    EpisodeSummary,
    ExperimentManifest,
    Limits,
    Mission,
    Origin,
    Outcome,
    RunMetadata,
    Scenario,
)
from dimos.experimental.domestic_assistance.rollouts import (
    DecisionFinished,
    DecisionStarted,
    EpisodeJournal,
    JournalEvent,
    audit_episode,
)
from dimos.experimental.domestic_assistance.runner import MissionRunner
from dimos.experimental.domestic_assistance.supervisor import ScriptedSupervisor
from dimos.experimental.domestic_assistance.testing_executor import (
    DeterministicExecutor,
    ManualClock,
)
from dimos.experimental.domestic_assistance.verification import DEFAULT_VERIFIER

PACKAGE_DIRECTORY = Path(__file__).parent
BASELINE_PATH = PACKAGE_DIRECTORY / "baselines" / "software_reference_v1.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_baseline() -> dict[str, Any]:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _run_reference_rollout(
    task: dict[str, Any], tmp_path: Path
) -> tuple[list[JournalEvent], EpisodeSummary]:
    mission_path = PACKAGE_DIRECTORY / task["mission_config"]
    scenario_path = PACKAGE_DIRECTORY / task["scenario_config"]
    mission = Mission.model_validate_json(mission_path.read_text(encoding="utf-8"))
    scenario = Scenario.model_validate_json(scenario_path.read_text(encoding="utf-8"))
    scenario.validate_mission(mission)
    assert mission.task_id == task["task_id"]

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
        relations=relations,
        bimanual_objects={
            goal.object_id for goal in mission.goals if goal.manipulation_mode == "bimanual"
        },
    )
    metadata = RunMetadata(
        episode_id=f"baseline-{mission.task_id}",
        scenario_id=scenario.scenario_id,
        session_id="phase-0",
        split_group=scenario.split_group,
        seed=0,
        origin=Origin.TEST,
        manifest=ExperimentManifest(
            experiment_id="domestic-assistance-software-reference-v1",
            method="software-test",
            code=ComponentManifest(name="domestic-assistance", version="phase-0"),
            supervisor=ComponentManifest(name="scripted-supervisor", version="scripted-v2"),
            executor=ComponentManifest(name="deterministic-executor", version="deterministic-v2"),
            verifier=ComponentManifest(
                name=DEFAULT_VERIFIER.name,
                version=DEFAULT_VERIFIER.version,
                sha256=DEFAULT_VERIFIER.fingerprint,
            ),
            mission_config_sha256=_sha256(mission_path),
            scenario_config_sha256=_sha256(scenario_path),
        ),
    )

    with EpisodeJournal(tmp_path, metadata.episode_id) as journal:
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
        for _ in range(200):
            runner.tick()
            clock.advance(0.1)
            if runner.summary is not None:
                break
        assert runner.summary is not None

    events = [
        JournalEvent.model_validate_json(line)
        for line in journal.path.read_text(encoding="utf-8").splitlines()
    ]
    return events, runner.summary


def test_phase_zero_freezes_schema_verifier_and_configuration_hashes():
    baseline = _load_baseline()

    assert baseline["baseline_id"] == "domestic-assistance-software-reference-v1"
    assert baseline["journal_schema_version"] == JournalEvent.model_fields["schema_version"].default
    assert baseline["verifier_name"] == "observed-facts"
    assert baseline["verifier_version"] == DEFAULT_VERIFIER.version
    assert baseline["verifier_sha256"] == DEFAULT_VERIFIER.fingerprint
    assert baseline["origin"] == Origin.TEST.value
    assert [task["task_id"] for task in baseline["tasks"]] == [
        "recoger_ropa",
        "preparar_bandeja",
    ]
    for task in baseline["tasks"]:
        mission_path = PACKAGE_DIRECTORY / task["mission_config"]
        scenario_path = PACKAGE_DIRECTORY / task["scenario_config"]
        assert _sha256(mission_path) == task["mission_config_sha256"]
        assert _sha256(scenario_path) == task["scenario_config_sha256"]


@pytest.mark.parametrize("task_id", ["recoger_ropa", "preparar_bandeja"])
def test_nominal_rollout_matches_frozen_phase_zero_reference(task_id, tmp_path):
    task = next(task for task in _load_baseline()["tasks"] if task["task_id"] == task_id)

    events, summary = _run_reference_rollout(task, tmp_path)
    started = [event.body for event in events if isinstance(event.body, DecisionStarted)]
    finished = [event.body for event in events if isinstance(event.body, DecisionFinished)]
    report = audit_episode(tmp_path / f"baseline-{task['task_id']}.jsonl")
    actual_summary = {name: getattr(summary, name) for name in task["expected_summary"]}

    assert len(events) == task["expected_events"]
    assert [item.decision.selected.skill for item in started] == task["expected_action_skills"]
    assert [item.history_entry.verification_result.predicate for item in finished] == task[
        "expected_verification_predicates"
    ]
    assert [item.history_entry.dispatch_status for item in finished] == [
        DispatchStatus.EXECUTED
    ] * task["expected_decisions"]
    assert [
        item.history_entry.executor_result.outcome
        if item.history_entry.executor_result is not None
        else None
        for item in finished
    ] == [Outcome.SUCCESS] * task["expected_decisions"]
    assert [item.history_entry.verification_result.outcome for item in finished] == [
        Outcome.SUCCESS
    ] * task["expected_decisions"]
    assert summary.decisions == task["expected_decisions"]
    assert actual_summary == task["expected_summary"]
    assert report.complete is True
    assert report.errors == ()
