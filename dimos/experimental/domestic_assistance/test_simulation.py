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
from pathlib import Path

import numpy as np
import pytest

from dimos.experimental.domestic_assistance.configuration import load_config_bundle
from dimos.experimental.domestic_assistance.contracts import (
    Action,
    ComponentManifest,
    ExperimentManifest,
    Limits,
    Origin,
    Outcome,
    RunMetadata,
)
from dimos.experimental.domestic_assistance.rollouts import EpisodeJournal, audit_episode
from dimos.experimental.domestic_assistance.runner import MissionRunner
from dimos.experimental.domestic_assistance.simulation import (
    DimosNavigationAdapter,
    SimulationExecutor,
    SimulationObserver,
    SymbolicSimulationWorld,
    load_simulation_zone_map,
)
from dimos.experimental.domestic_assistance.supervisor import ScriptedSupervisor
from dimos.experimental.domestic_assistance.testing_executor import ManualClock
from dimos.experimental.domestic_assistance.verification import DEFAULT_VERIFIER
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.sensor_msgs.Image import Image
from dimos.navigation.base import NavigationState

CONFIG_DIRECTORY = Path(__file__).parent / "configs"


class FakeNavigation:
    def __init__(self) -> None:
        self.state = NavigationState.IDLE
        self.reached = False
        self.goal: PoseStamped | None = None
        self.cancel_requests = 0

    def set_goal(self, goal: PoseStamped) -> bool:
        self.goal = goal
        self.reached = False
        self.state = NavigationState.FOLLOWING_PATH
        return True

    def get_state(self) -> NavigationState:
        return self.state

    def is_goal_reached(self) -> bool:
        return self.reached

    def cancel_goal(self) -> bool:
        self.cancel_requests += 1
        return True

    def arrive(self) -> None:
        self.reached = True
        self.state = NavigationState.IDLE

    def confirm_cancel(self) -> None:
        self.reached = False
        self.state = NavigationState.IDLE


class DelayedMapNavigation(FakeNavigation):
    def __init__(self) -> None:
        super().__init__()
        self.map_ready = False

    def set_goal(self, goal: PoseStamped) -> bool:
        if not self.map_ready:
            raise ValueError("No current global costmap available")
        return super().set_goal(goal)


def _load(task_id: str = "recoger_ropa"):
    bundle = load_config_bundle(
        CONFIG_DIRECTORY / f"{task_id}.json",
        CONFIG_DIRECTORY / f"{task_id}_nominal.json",
    )
    zone_bundle = load_simulation_zone_map(
        CONFIG_DIRECTORY / f"{task_id}_simulation_zones.json", bundle.mission
    )
    return bundle, zone_bundle


def _image(timestamp: float) -> Image:
    return Image.from_numpy(
        np.full((8, 12, 3), 127, dtype=np.uint8),
        frame_id="front_camera",
        ts=timestamp,
    )


def _feed(
    observer: SimulationObserver,
    clock: ManualClock,
    x: float,
    y: float,
    *,
    camera: bool = True,
) -> None:
    timestamp = clock.time()
    observer.update_odom(PoseStamped(ts=timestamp, frame_id="world", position=[x, y, 0.0]))
    if camera:
        observer.update_camera("front_camera", _image(timestamp))


@pytest.mark.parametrize("task_id", ["recoger_ropa", "preparar_bandeja"])
def test_zone_map_is_versioned_hashed_and_matches_mission(task_id):
    bundle, zone_bundle = _load(task_id)
    source = CONFIG_DIRECTORY / f"{task_id}_simulation_zones.json"

    assert set(item.zone for item in zone_bundle.zone_map.zones) == set(bundle.mission.zones)
    assert zone_bundle.config_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()


def test_navigation_acceptance_is_not_completion_and_cancel_waits_for_idle():
    bundle, zone_bundle = _load()
    del bundle
    clock = ManualClock()
    backend = FakeNavigation()
    navigation = DimosNavigationAdapter(backend, zone_bundle.zone_map, clock)

    navigation.start("decision-0001", "suelo_centro")
    assert backend.goal is not None
    assert navigation.poll("decision-0001") is None
    assert navigation.is_idle() is False

    navigation.cancel("decision-0001")
    assert backend.cancel_requests == 1
    assert navigation.is_idle() is False
    backend.confirm_cancel()
    assert navigation.is_idle() is True


def test_navigation_reports_success_only_after_planner_arrival():
    _, zone_bundle = _load()
    clock = ManualClock()
    backend = FakeNavigation()
    navigation = DimosNavigationAdapter(backend, zone_bundle.zone_map, clock)

    navigation.start("decision-0001", "suelo_centro")
    backend.arrive()
    result = navigation.poll("decision-0001")

    assert result is not None
    assert result.outcome == Outcome.SUCCESS
    assert navigation.is_idle() is True


def test_navigation_waits_for_transient_costmap_readiness():
    _, zone_bundle = _load()
    clock = ManualClock()
    backend = DelayedMapNavigation()
    navigation = DimosNavigationAdapter(backend, zone_bundle.zone_map, clock)

    navigation.start("decision-0001", "suelo_centro")
    assert backend.goal is None
    assert navigation.poll("decision-0001") is None
    assert navigation.is_idle() is False

    backend.map_ready = True
    assert navigation.poll("decision-0001") is None
    assert backend.goal is not None
    backend.arrive()
    result = navigation.poll("decision-0001")
    assert result is not None
    assert result.outcome == Outcome.SUCCESS


def test_cancel_reaches_backend_while_costmap_is_not_ready():
    _, zone_bundle = _load()
    backend = DelayedMapNavigation()
    navigation = DimosNavigationAdapter(backend, zone_bundle.zone_map, ManualClock())

    navigation.start("decision-0001", "suelo_centro")
    navigation.cancel("decision-0001")

    assert backend.cancel_requests == 1
    assert navigation.is_idle() is True


def test_observer_requires_synced_sensors_and_pose_stability(tmp_path):
    bundle, zone_bundle = _load()
    backend = FakeNavigation()
    world = SymbolicSimulationWorld(bundle.mission, bundle.scenario)
    observer = SimulationObserver(backend, zone_bundle.zone_map, world, tmp_path / "evidence")
    clock = ManualClock()

    _feed(observer, clock, -1.0, 1.0, camera=False)
    with pytest.raises(ValueError, match="incomplete or unsynchronized"):
        observer.observe()

    observer.update_camera("front_camera", _image(clock.time() - 1.0))
    with pytest.raises(ValueError, match="incomplete or unsynchronized"):
        observer.observe()

    for _ in range(3):
        clock.advance(0.1)
        _feed(observer, clock, -1.0, 1.0)
    observation = observer.observe()

    assert observation.origin == Origin.SIMULATION
    assert observation.robot.zone == "suelo_norte"
    assert observation.base_stopped is True
    assert len(observation.keyframes) == 1
    keyframe = observation.keyframes[0]
    assert Path(keyframe.path).is_file()
    assert keyframe.sha256 == hashlib.sha256(Path(keyframe.path).read_bytes()).hexdigest()
    assert {item.evidence[0].source for item in observation.objects} == {
        "symbolic-simulation-state"
    }

    completion_time = clock.time()
    clock.advance(0.1)
    _feed(observer, clock, -1.0, 1.0, camera=False)
    assert observer.observe_after(completion_time) is None
    observer.update_camera("front_camera", _image(clock.time()))
    assert observer.observe_after(completion_time) is not None


def test_composite_navigation_waits_for_pose_derived_stop(tmp_path):
    bundle, zone_bundle = _load()
    backend = FakeNavigation()
    clock = ManualClock()
    world = SymbolicSimulationWorld(bundle.mission, bundle.scenario)
    observer = SimulationObserver(backend, zone_bundle.zone_map, world, tmp_path)
    navigation = DimosNavigationAdapter(backend, zone_bundle.zone_map, clock)
    executor = SimulationExecutor(navigation, world, observer, clock)

    for _ in range(3):
        _feed(observer, clock, -1.0, 1.0)
        clock.advance(0.1)
    executor.start("decision-0001", Action(skill="NAVIGATE", zone="suelo_centro"))
    assert backend.goal is not None
    backend.arrive()
    _feed(observer, clock, backend.goal.x, backend.goal.y)
    assert executor.poll("decision-0001") is None

    for _ in range(2):
        clock.advance(0.1)
        _feed(observer, clock, backend.goal.x, backend.goal.y)
    result = executor.poll("decision-0001")

    assert result is not None
    assert result.outcome == Outcome.SUCCESS
    assert executor.is_idle() is True


@pytest.mark.parametrize("task_id", ["recoger_ropa", "preparar_bandeja"])
def test_full_nominal_simulation_uses_runner_journal_and_verifier(task_id, tmp_path):
    bundle, zone_bundle = _load(task_id)
    backend = FakeNavigation()
    clock = ManualClock()
    world = SymbolicSimulationWorld(bundle.mission, bundle.scenario)
    observer = SimulationObserver(backend, zone_bundle.zone_map, world, tmp_path / "evidence")
    navigation = DimosNavigationAdapter(backend, zone_bundle.zone_map, clock)
    executor = SimulationExecutor(navigation, world, observer, clock)
    initial = zone_bundle.zone_map.pose_for(bundle.scenario.initial_robot_zone)
    current_xy = (initial.x, initial.y)
    for _ in range(3):
        _feed(observer, clock, *current_xy)
        clock.advance(0.1)

    metadata = RunMetadata(
        episode_id=f"simulation-{task_id}",
        scenario_id=bundle.scenario.scenario_id,
        session_id="phase-2-test",
        split_group=bundle.scenario.split_group,
        seed=0,
        origin=Origin.SIMULATION,
        manifest=ExperimentManifest(
            experiment_id="domestic-assistance-phase-2-test",
            method="software-test",
            code=ComponentManifest(name="domestic-assistance", version="phase-2"),
            supervisor=ComponentManifest(name="scripted-supervisor", version="scripted-v2"),
            executor=ComponentManifest(name="dimos-symbolic-simulation", version="phase-2"),
            verifier=ComponentManifest(
                name=DEFAULT_VERIFIER.name,
                version=DEFAULT_VERIFIER.version,
                sha256=DEFAULT_VERIFIER.fingerprint,
            ),
            mission_config_sha256=bundle.mission_config_sha256,
            scenario_config_sha256=bundle.scenario_config_sha256,
            environment_config_sha256=zone_bundle.config_sha256,
        ),
    )
    with EpisodeJournal(tmp_path / "journals", metadata.episode_id) as journal:
        runner = MissionRunner(
            bundle.mission,
            metadata,
            executor,
            observer,
            ScriptedSupervisor(bundle.scenario.nominal_actions),
            journal,
            limits=Limits(
                mission_timeout_s=120,
                skill_timeout_s=10,
                verification_timeout_s=2,
                cancellation_timeout_s=1,
            ),
            clock=clock,
        )
        for _ in range(600):
            if backend.state == NavigationState.FOLLOWING_PATH:
                assert backend.goal is not None
                current_xy = (backend.goal.x, backend.goal.y)
                backend.arrive()
            _feed(observer, clock, *current_xy)
            runner.tick()
            if runner.summary is not None:
                break
            clock.advance(0.1)
        else:
            raise AssertionError("simulation episode did not terminate")

    assert runner.summary is not None
    assert runner.summary.reason == "SUCCESS"
    assert runner.summary.decisions == len(bundle.scenario.nominal_actions)
    report = audit_episode(journal.path)
    assert report.origin == Origin.SIMULATION
    assert report.complete is True
    assert report.errors == ()
