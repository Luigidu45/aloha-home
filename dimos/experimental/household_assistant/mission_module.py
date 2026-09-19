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

"""DimOS runtime for F4: responsive control loop and a separate simulation adapter."""

from collections import deque
from pathlib import Path
from queue import Empty, Queue
import threading
import time
from typing import Any, Protocol

from pydantic import Field

from dimos.core.core import rpc
from dimos.core.module import Module, ModuleConfig
from dimos.core.stream import Out
from dimos.experimental.household_assistant.configuration import PilotConfiguration, load_pilot
from dimos.experimental.household_assistant.contracts import ActionProposal, MissionRequest
from dimos.experimental.household_assistant.mission import MissionManager
from dimos.experimental.household_assistant.mission_contracts import (
    Arm,
    ExecutorCommand,
    ExecutorResult,
    MissionEvent,
    MissionPlanningState,
    MissionSnapshot,
    WorldFrame,
)
from dimos.experimental.household_assistant.mission_sequence import MissionSequence
from dimos.experimental.household_assistant.mission_simulation import (
    ArtificialMissionExecutor,
    Scenario,
    SpatialPort,
    simulation_bindings,
)
from dimos.experimental.household_assistant.spatial import SPATIAL_SIM_CONFIG
from dimos.spec.utils import Spec


class HouseholdSpatialSpec(SpatialPort, Spec, Protocol):
    pass


class ExecutorMailbox:
    """Single-owner adapter results and cancellable command handoff, without motor calls."""

    def __init__(self, pilot: PilotConfiguration, arm: Arm) -> None:
        self.pilot = pilot
        self.arm = arm
        self.clock_id = "unix"
        self.incoming: Queue[WorldFrame | ExecutorResult] = Queue()
        self._lock = threading.Lock()
        self._commands: deque[ExecutorCommand] = deque()

    def enqueue(self, commands: tuple[ExecutorCommand, ...]) -> None:
        with self._lock:
            for command in commands:
                if command.kind == "stop":
                    self._commands.clear()
                self._commands.append(command)

    def take_commands(self) -> tuple[ExecutorCommand, ...]:
        with self._lock:
            commands = tuple(self._commands)
            self._commands.clear()
            return commands

    def receive(self, result: ExecutorResult, *, now: float) -> None:
        self.incoming.put(result)

    def update_world(self, frame: WorldFrame, *, now: float) -> None:
        self.incoming.put(frame)


class HouseholdMissionConfig(ModuleConfig):
    pilot_path: Path = SPATIAL_SIM_CONFIG.with_name("pilot.json")
    arm: Arm = "right"
    scenario: Scenario = "nominal"
    automatic_sequence: bool = True
    tick_s: float = Field(default=0.1, gt=0)
    fixture_action_s: float = Field(default=0.3, gt=0)
    stop_timeout_s: float = Field(default=5.0, gt=0)


class HouseholdMissionModule(Module):
    """Simulation-only mission RPCs. F5 will expose admitted proposals through MCP."""

    config: HouseholdMissionConfig
    mission_status: Out[MissionSnapshot]
    mission_event: Out[MissionEvent]
    _spatial: HouseholdSpatialSpec

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        pilot = load_pilot(self.config.pilot_path)
        self._manager = MissionManager(
            pilot,
            simulation_bindings(pilot, real_navigation=True),
            arm=self.config.arm,
            stop_timeout_s=self.config.stop_timeout_s,
        )
        self._mailbox = ExecutorMailbox(pilot, self.config.arm)
        self._control = threading.RLock()
        self._shutdown = threading.Event()
        self._threads: list[threading.Thread] = []
        self._sequence: MissionSequence | None = None
        self._frame: WorldFrame | None = None
        self._published_sequence = -1
        self._adapter_error = ""

    @rpc
    def start(self) -> None:
        super().start()
        executor = ArtificialMissionExecutor(
            self._mailbox,
            spatial=self._spatial,
            scenario=self.config.scenario,
            duration_s=self.config.fixture_action_s,
            wall_clock=time.time,
        )
        self._shutdown.clear()
        self._threads = [
            threading.Thread(target=self._run_control, name="HouseholdMissionControl", daemon=True),
            threading.Thread(
                target=self._run_adapter,
                args=(executor,),
                name="HouseholdMissionAdapter",
                daemon=True,
            ),
        ]
        for thread in self._threads:
            thread.start()

    @rpc
    def get_mission_status(self) -> MissionSnapshot:
        return self._manager.snapshot()

    @rpc
    def get_mission_events(self) -> tuple[MissionEvent, ...]:
        return self._manager.events()

    @rpc
    def get_world_frame(self) -> WorldFrame | None:
        with self._control:
            return self._frame.model_copy(deep=True) if self._frame else None

    @rpc
    def get_planning_state(self) -> MissionPlanningState:
        return self._manager.planning_state()

    @rpc
    def admit_planner_json(
        self,
        expected_json: str,
        request_json: str,
        action_json: str,
        question: str,
        target: str,
    ) -> MissionSnapshot:
        """F5 proposals enter the same atomic admission gate as all other actions."""
        if self.config.automatic_sequence:
            raise RuntimeError("disable the F4 scripted sequence before enabling F5")
        with self._control:
            result = self._manager.admit_planner(
                expected=MissionSnapshot.model_validate_json(expected_json),
                request=MissionRequest.model_validate_json(request_json) if request_json else None,
                action=ActionProposal.model_validate_json(action_json) if action_json else None,
                question=question or None,
                target=target or None,
                now=time.time(),
            )
            self._mailbox.enqueue(self._manager.take_commands())
            return result

    @rpc
    def ask_mission(self, question: str) -> None:
        with self._control:
            self._manager.ask(question, now=time.time())

    @rpc
    def submit_request(self, request_json: str) -> MissionSnapshot:
        """Accept a normalized F1 request, not free-form language interpretation."""
        request = MissionRequest.model_validate_json(request_json)
        with self._control:
            before = self._manager.snapshot().request_id
            result = self._manager.submit(request, now=time.time())
            if before != result.request_id and result.state == "preparing":
                self._sequence = MissionSequence(self._manager, request)
            return result

    @rpc
    def propose_action(self, action_json: str, expected_revision: int) -> MissionSnapshot:
        """Admit a structured proposal after checking its scene revision and live facts."""
        with self._control:
            result = self._manager.propose(
                ActionProposal.model_validate_json(action_json),
                expected_revision=expected_revision,
                now=time.time(),
            )
            self._mailbox.enqueue(self._manager.take_commands())
            return result

    @rpc
    def choose_target(self, object_id: str, expected_revision: int) -> MissionSnapshot:
        """Answer a target ambiguity using a currently observed logical object binding."""
        with self._control:
            return self._manager.select_target(
                object_id, expected_revision=expected_revision, now=time.time()
            )

    @rpc
    def cancel_mission(self, pause: bool = False) -> MissionSnapshot:
        """Request cancellation; get_mission_status reports when stop is observed."""
        with self._control:
            result = self._manager.cancel(now=time.time(), pause=pause)
            self._mailbox.enqueue(self._manager.take_commands())
            return result

    @rpc
    def resume_mission(self) -> MissionSnapshot:
        """Reprepare after observed stop and payload reconciliation, never replay a chunk."""
        with self._control:
            return self._manager.resume(now=time.time())

    def _run_adapter(self, executor: ArtificialMissionExecutor) -> None:
        try:
            while not self._shutdown.wait(self.config.tick_s):
                executor.step(now=time.time())
        except Exception as exc:
            # The independent control loop times out stale sensors and latches stop.
            with self._control:
                self._adapter_error = f"{type(exc).__name__}:{exc}"
                self._manager.fail(f"adapter_error:{self._adapter_error}", now=time.time())
                self._mailbox.enqueue(self._manager.take_commands())

    def _poll(self) -> tuple[MissionSnapshot, tuple[MissionEvent, ...]]:
        with self._control:
            while True:
                try:
                    item = self._mailbox.incoming.get_nowait()
                except Empty:
                    break
                now = time.time()
                if isinstance(item, WorldFrame):
                    self._manager.update_world(item, now=now)
                    self._frame = item
                else:
                    self._manager.receive(item, now=now)
            now = time.time()
            self._manager.tick(now=now)
            if self.config.automatic_sequence and self._sequence and self._frame:
                self._sequence.advance(self._frame, now=now)
            self._mailbox.enqueue(self._manager.take_commands())
            events = self._manager.events(self._published_sequence)
            if events:
                self._published_sequence = events[-1].sequence
            return self._manager.snapshot(), events

    def _run_control(self) -> None:
        while not self._shutdown.wait(self.config.tick_s):
            try:
                status, events = self._poll()
                self.mission_status.publish(status)
                for event in events:
                    self.mission_event.publish(event)
            except Exception as exc:
                # A malformed incoming frame or failed publisher must not silently
                # kill the watchdog. Keep servicing cancellation and stop evidence.
                with self._control:
                    self._adapter_error = f"control_error:{type(exc).__name__}:{exc}"
                    self._manager.fail(self._adapter_error, now=time.time())
                    self._mailbox.enqueue(self._manager.take_commands())

    @rpc
    def stop(self) -> None:
        if self._shutdown.is_set():
            return
        try:
            self.cancel_mission()
            deadline = time.monotonic() + self.config.stop_timeout_s + 1
            wait = threading.Event()
            while (
                self._manager.snapshot().state in {"stopping", "stop_unconfirmed"}
                and time.monotonic() < deadline
            ):
                wait.wait(self.config.tick_s)
        finally:
            self._shutdown.set()
            for thread in self._threads:
                if thread is not threading.current_thread():
                    thread.join(timeout=self.config.stop_timeout_s)
            super().stop()
        if any(t.is_alive() for t in self._threads):
            raise RuntimeError("mission adapter did not terminate; stop remains unconfirmed")

    @rpc
    def get_adapter_error(self) -> str:
        with self._control:
            return self._adapter_error


household_mission_module = HouseholdMissionModule.blueprint
