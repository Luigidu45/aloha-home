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

"""Owned live camera/VLM loop; HTTP controls never wait for model inference."""

import threading
import time

from dimos.experimental.household_assistant.configuration import PilotConfiguration
from dimos.experimental.household_assistant.contracts import ActionProposal, MissionRequest, Origin
from dimos.experimental.household_assistant.mission_contracts import Arm, MissionSnapshot
from dimos.experimental.household_assistant.mission_module import HouseholdMissionModule
from dimos.experimental.household_assistant.planner import PlannerSupervisor
from dimos.experimental.household_assistant.planner_backend import LocalVLM
from dimos.experimental.household_assistant.planner_contracts import PlannerConfig, PlannerContext
from dimos.experimental.household_assistant.planner_resources import PlannerResources
from dimos.experimental.household_assistant.spatial_module import HouseholdSpatialModule
from dimos.experimental.household_assistant.web_session import AssistanceSession


class SessionMissionPort:
    def __init__(
        self,
        session: AssistanceSession,
        module: HouseholdMissionModule,
        pilot: PilotConfiguration,
        generation: int,
    ) -> None:
        self.session, self.module, self.pilot = session, module, pilot
        self.generation = generation
        self.arm: Arm = "right"
        self.max_age_s = 2.0

    def snapshot(self) -> MissionSnapshot:
        return self.module.get_mission_status()

    def ask(self, reason: str, *, now: float) -> None:
        with self.session.lock:
            if self.session.generation == self.generation and self.session.enabled:
                self.module.ask_mission(reason)

    def admit_planner(
        self,
        *,
        expected: MissionSnapshot,
        request: MissionRequest | None,
        action: ActionProposal | None,
        question: str | None,
        target: str | None,
        now: float,
    ) -> MissionSnapshot:
        with self.session.lock:
            if self.session.generation != self.generation or not self.session.enabled:
                raise ValueError("operator changed/cancelled the conversation")
            return self.module.admit_planner_json(
                expected.model_dump_json(),
                request.model_dump_json() if request else "",
                action.model_dump_json() if action else "",
                question or "",
                target or "",
            )


class AssistanceRuntime:
    def __init__(
        self,
        session: AssistanceSession,
        module: HouseholdMissionModule,
        spatial: HouseholdSpatialModule,
        pilot: PilotConfiguration,
        config: PlannerConfig,
        backend: LocalVLM | None,
        resources: PlannerResources | None,
    ) -> None:
        self.session, self.module, self.spatial = session, module, spatial
        self.pilot, self.config, self.backend, self.resources = pilot, config, backend, resources
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="household-web-planner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.module.cancel_mission()
        if self._thread:
            self._thread.join(timeout=self.config.startup_timeout_s + 10)
            if self._thread.is_alive():
                raise RuntimeError("planner thread did not stop")

    def _run(self) -> None:
        supervisor: PlannerSupervisor | None = None
        pending: PlannerContext | None = None
        generation = -1
        backend_ready = False
        last_state: str | None = None
        try:
            if self.resources:
                self.resources.start()
            while not self._stop.wait(0.15):
                bundle = self.module.get_planning_state()
                if bundle.state.state != last_state:
                    self.session.record("mission_state", state=bundle.state.model_dump(mode="json"))
                    last_state = bundle.state.state
                capture = self.spatial.get_planner_image()
                if capture:
                    image, view = capture
                    pose = view.observer_pose
                    self.session.update_media(
                        image.to_jpeg_bytes(quality=75),
                        image.ts,
                        {"x": pose.x, "y": pose.y, "yaw": pose.yaw, "ts": pose.ts},
                    )
                with self.session.lock:
                    current_generation = self.session.generation
                    enabled = self.session.enabled
                if generation != current_generation:
                    if supervisor:
                        self.session.record("planner_trace", records=supervisor.records)
                        supervisor.close()
                        backend_ready = False
                    supervisor, pending = None, None
                    generation = current_generation
                    with self.session.lock:
                        self.session.busy = False
                if not enabled or self.backend is None or self.resources is None:
                    continue
                if not capture or bundle.request is None or bundle.world is None:
                    continue
                if bundle.state.action or bundle.state.state not in {"preparing", "searching"}:
                    continue
                if supervisor is None:
                    if not backend_ready:
                        with self.session.lock:
                            self.session.busy = True
                        self.backend.start()
                        backend_ready = True
                    supervisor = PlannerSupervisor(
                        SessionMissionPort(self.session, self.module, self.pilot, generation),
                        self.backend,
                        self.config,
                    )
                    continue  # Refresh images/world after model loading.
                image, view = capture
                if pending is None:
                    observation = self.resources.perception.observe(image, view, "small_bottle")
                    memory = self.resources.memory.candidates(
                        "small_bottle",
                        map_id=view.map_id,
                        origin=Origin.SIMULATION,
                        clock_id="unix",
                        limit=3,
                    )
                    context = PlannerContext(
                        instruction=bundle.request.instruction,
                        request=bundle.request,
                        state=bundle.state,
                        world=bundle.world,
                        views=(view,),
                        memory=memory,
                        perception=(observation,),
                        catalog=tuple(
                            s for s in self.pilot.skills if s.id != "pick_remote_from_floor"
                        ),
                        previous_result=bundle.state.reason,
                    )
                    try:
                        supervisor.begin(context, (image,), now=time.time())
                    except ValueError:
                        continue  # Wait for a current stopped snapshot, never bypass it.
                    self.resources.memory.remember(image, view)
                    pending = context
                    with self.session.lock:
                        self.session.busy = True
                else:
                    current = pending.model_copy(
                        update={"state": bundle.state, "world": bundle.world, "views": (view,)}
                    )
                    status = supervisor.poll(current, (image,), now=time.time())
                    if status == "pending":
                        continue
                    with self.session.lock:
                        self.session.busy = False
                    if status == "admitted":
                        decision = supervisor.last_decision
                        if decision and decision.question:
                            self.session.planner_message(decision.question, generation=generation)
                        pending = None
                    else:
                        self.session.record("planner_trace", records=supervisor.records)
                        with self.session.lock:
                            if self.session.generation == generation:
                                self.module.cancel_mission(pause=True)
                                self.session.enabled = False
                        self.session.planner_message(
                            "La escena cambió o el modelo no respondió de forma válida. Se solicitó una pausa; revisa antes de reanudar.",
                            generation=generation,
                        )
                        pending = None
        except Exception as exc:
            self.session.record("runtime_error", error=str(exc))
            self.module.cancel_mission(pause=True)
            with self.session.lock:
                self.session.enabled = False
                self.session.busy = False
                self.session.message = "El servicio visual se interrumpió. Se solicitó la parada; reinicia la sesión tras comprobar el estado."
        finally:
            if supervisor:
                self.session.record("planner_trace", records=supervisor.records)
                supervisor.close()
            elif self.backend:
                self.backend.close()
            if self.resources:
                self.resources.close()
