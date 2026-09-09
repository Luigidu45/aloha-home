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

"""DimOS module that owns one simulated domestic-assistance episode."""

from pathlib import Path
from threading import Event, RLock, Thread
from typing import Annotated, Any

from pydantic import Field
from reactivex.disposable import Disposable

from dimos.core.core import rpc
from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import In
from dimos.experimental.domestic_assistance.configuration import ConfigBundle, load_config_bundle
from dimos.experimental.domestic_assistance.contracts import (
    ComponentManifest,
    ExperimentManifest,
    Limits,
    Origin,
    RunMetadata,
)
from dimos.experimental.domestic_assistance.rollouts import EpisodeJournal
from dimos.experimental.domestic_assistance.runner import MissionRunner, SystemClock
from dimos.experimental.domestic_assistance.simulation import (
    DimosNavigationAdapter,
    SimulationExecutor,
    SimulationObserver,
    SimulationZoneBundle,
    SymbolicSimulationWorld,
    load_simulation_zone_map,
)
from dimos.experimental.domestic_assistance.supervisor import ScriptedSupervisor
from dimos.experimental.domestic_assistance.verification import DEFAULT_VERIFIER
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.sensor_msgs.Image import Image
from dimos.navigation.navigation_spec import NavigationInterfaceSpec


class DomesticAssistanceSimulationConfig(ModuleConfig):
    mission_path: Path
    scenario_path: Path
    zone_map_path: Path
    output_directory: Path = Path("/tmp/dimos-domestic-assistance")
    tick_hz: Annotated[float, Field(gt=0)] = 10.0
    required_camera: str = "front_camera"


class DomesticAssistanceSimulationModule(Module):
    """Connect navigation and sensor streams to the auditable mission lifecycle."""

    config: DomesticAssistanceSimulationConfig

    odom: In[PoseStamped]
    front_camera_image: In[Image]

    _navigation: NavigationInterfaceSpec

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._lock = RLock()
        self._clock = SystemClock()
        self._runner: MissionRunner | None = None
        self._journal: EpisodeJournal | None = None
        self._observer: SimulationObserver | None = None
        self._executor: SimulationExecutor | None = None
        self._bundle: ConfigBundle | None = None
        self._zone_bundle: SimulationZoneBundle | None = None
        self._episode_thread: Thread | None = None
        self._stop_loop = Event()
        self._last_error: str | None = None

    @rpc
    def start(self) -> None:
        super().start()
        bundle = load_config_bundle(self.config.mission_path, self.config.scenario_path)
        zone_bundle = load_simulation_zone_map(self.config.zone_map_path, bundle.mission)
        world = SymbolicSimulationWorld(bundle.mission, bundle.scenario)
        evidence_directory = self.config.output_directory / "evidence"
        observer = SimulationObserver(
            self._navigation,
            zone_bundle.zone_map,
            world,
            evidence_directory,
            required_cameras=(self.config.required_camera,),
        )
        navigation = DimosNavigationAdapter(self._navigation, zone_bundle.zone_map, self._clock)
        self._observer = observer
        self._executor = SimulationExecutor(navigation, world, observer, self._clock)
        self._bundle = bundle
        self._zone_bundle = zone_bundle
        self.register_disposable(Disposable(self.odom.subscribe(observer.update_odom)))
        self.register_disposable(
            Disposable(
                self.front_camera_image.subscribe(
                    lambda image: observer.update_camera(self.config.required_camera, image)
                )
            )
        )

    @rpc
    def stop(self) -> None:
        self._stop_active_episode()
        super().stop()

    @rpc
    def start_nominal_episode(self, episode_id: str, seed: int = 0) -> str:
        """Start the configured nominal scenario after synchronized sensors are ready."""
        with self._lock:
            if self._observer is None or self._executor is None:
                raise RuntimeError("simulation module is not started")
            if self._bundle is None or self._zone_bundle is None:
                raise RuntimeError("simulation configuration is unavailable")
            if not self._observer.ready:
                raise RuntimeError("waiting for synchronized odometry and camera data")
            if self._episode_thread is not None and self._episode_thread.is_alive():
                raise RuntimeError("an episode is already active")
            if self._runner is not None:
                raise RuntimeError("restart the blueprint before resetting the symbolic world")
            self._last_error = None
            self._stop_loop.clear()
            metadata = RunMetadata(
                episode_id=episode_id,
                scenario_id=self._bundle.scenario.scenario_id,
                session_id="dimos-mujoco",
                split_group=self._bundle.scenario.split_group,
                seed=seed,
                origin=Origin.SIMULATION,
                manifest=ExperimentManifest(
                    experiment_id="domestic-assistance-phase-2",
                    method="software-test",
                    code=ComponentManifest(name="domestic-assistance", version="phase-2"),
                    supervisor=ComponentManifest(name="scripted-supervisor", version="scripted-v2"),
                    executor=ComponentManifest(name="dimos-symbolic-simulation", version="phase-2"),
                    verifier=ComponentManifest(
                        name=DEFAULT_VERIFIER.name,
                        version=DEFAULT_VERIFIER.version,
                        sha256=DEFAULT_VERIFIER.fingerprint,
                    ),
                    mission_config_sha256=self._bundle.mission_config_sha256,
                    scenario_config_sha256=self._bundle.scenario_config_sha256,
                    environment_config_sha256=self._zone_bundle.config_sha256,
                ),
            )
            journal = EpisodeJournal(self.config.output_directory / "journals", episode_id)
            self._journal = journal
            self._runner = MissionRunner(
                self._bundle.mission,
                metadata,
                self._executor,
                self._observer,
                ScriptedSupervisor(self._bundle.scenario.nominal_actions),
                journal,
                limits=Limits(),
                clock=self._clock,
            )
            self._episode_thread = Thread(
                target=self._run_episode,
                name=f"domestic-sim-{episode_id}",
                daemon=True,
            )
            self._episode_thread.start()
            return str(journal.path)

    @rpc
    def cancel_episode(self) -> bool:
        """Request cancellation; the loop keeps ticking until stop is confirmed."""
        with self._lock:
            if self._runner is None or self._runner.summary is not None:
                return False
            self._runner.cancel()
            return True

    @rpc
    def episode_status(self) -> dict[str, Any]:
        """Return readiness, active state, terminal summary and any loop error."""
        with self._lock:
            summary = self._runner.summary if self._runner is not None else None
            return {
                "sensors_ready": bool(self._observer and self._observer.ready),
                "active": bool(self._episode_thread and self._episode_thread.is_alive()),
                "journal": str(self._journal.path) if self._journal is not None else None,
                "summary": summary.model_dump(mode="json") if summary is not None else None,
                "error": self._last_error,
                "manipulation_mode": "symbolic",
            }

    def _run_episode(self) -> None:
        try:
            while not self._stop_loop.is_set():
                with self._lock:
                    runner = self._runner
                if runner is None:
                    return
                summary = runner.tick()
                if summary is not None:
                    return
                self._stop_loop.wait(1.0 / self.config.tick_hz)
        except Exception as exc:
            with self._lock:
                self._last_error = f"{type(exc).__name__}: {exc}"
        finally:
            with self._lock:
                if self._journal is not None:
                    self._journal.close()

    def _stop_active_episode(self) -> None:
        with self._lock:
            runner = self._runner
            thread = self._episode_thread
            if runner is not None and runner.summary is None:
                runner.cancel()
        if thread is not None and thread.is_alive():
            thread.join(timeout=6.0)
        self._stop_loop.set()
