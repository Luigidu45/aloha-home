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

"""Explicit artificial manipulation fixture, optionally attached to real F2 navigation.

This adapter NEVER sends arm/elevator/gripper commands. The object does not move
in MuJoCo: object, wrist, alignment and load signals below are TEST evidence.
Navigation and base-stop evidence, when attached, come from F2 pose samples.
"""

from collections.abc import Callable
from typing import Literal, Protocol

from dimos.experimental.household_assistant.configuration import PilotConfiguration
from dimos.experimental.household_assistant.contracts import (
    Evidence,
    Observation,
    Operation,
    Origin,
    Predicate,
)
from dimos.experimental.household_assistant.mission_contracts import (
    Arm,
    ExecutorBinding,
    ExecutorCommand,
    ExecutorResult,
    WorldFrame,
)
from dimos.experimental.household_assistant.mission_verification import fact
from dimos.experimental.household_assistant.spatial import PoseWindow, Purpose, SpatialStatus
from dimos.experimental.household_assistant.spatial_module import SpatialSnapshot

Scenario = Literal[
    "nominal",
    "absent",
    "ambiguous",
    "unknown",
    "grasp_failure",
    "unverified_grasp",
    "timeout",
    "retention_loss",
    "posture_loss",
    "occupied",
    "disconnect",
    "stop_unconfirmed",
]


class ExecutorManagerPort(Protocol):
    pilot: PilotConfiguration
    arm: Arm
    clock_id: str

    def take_commands(self) -> tuple[ExecutorCommand, ...]: ...
    def receive(self, result: ExecutorResult, *, now: float) -> None: ...
    def update_world(self, frame: WorldFrame, *, now: float) -> None: ...


class SpatialPort(Protocol):
    def go_to(self, place_id: str, purpose: Purpose = "observe") -> SpatialStatus: ...
    def cancel(self) -> SpatialStatus: ...
    def get_status(self) -> SpatialStatus: ...
    def get_observation(self, place_id: str) -> SpatialSnapshot | None: ...


def simulation_bindings(
    pilot: PilotConfiguration, *, real_navigation: bool = False
) -> tuple[ExecutorBinding, ...]:
    return tuple(
        ExecutorBinding(
            id=s.executor_id,
            operations=(s.operation,),
            origin=Origin.SIMULATION
            if real_navigation and s.operation == Operation.NAVIGATE
            else Origin.TEST,
            artificial=not (real_navigation and s.operation == Operation.NAVIGATE),
        )
        for s in pilot.skills
    )


class ArtificialMissionExecutor:
    """Single-owner fixture. Call step on its adapter thread, not in manager RPCs.

    `scenario` injects faults into the fixture; it is not an override of real
    observations. `latest_frame` is only read by that same owner.
    """

    def __init__(
        self,
        manager: ExecutorManagerPort,
        *,
        spatial: SpatialPort | None = None,
        scenario: Scenario = "nominal",
        duration_s: float = 0.2,
        wall_clock: Callable[[], float] | None = None,
    ) -> None:
        self.manager = manager
        self._wall_clock = wall_clock
        self.spatial = spatial
        self.scenario = scenario
        self.duration_s = duration_s
        self.active: ExecutorCommand | None = None
        self.started = 0.0
        self.finished = False
        self.stopping = False
        self.stop_at = 0.0
        self.nav_request = ""
        self.place = "initial"
        self.aligned = ""
        self.held: str | None = None
        self.loaded = False
        self.placed: str | None = None
        self.grasp_unknown = False
        self.disconnected = False
        self.latest_frame: WorldFrame | None = None
        self.last_snapshot: SpatialSnapshot | None = None
        self.dispatched: list[ExecutorCommand] = []
        self._revision = 0
        self._signature: tuple[str, ...] = ()
        self._poses = PoseWindow(
            settle_s=0.15,
            max_age_s=1.0,
            linear_stop_mps=0.03,
            angular_stop_rps=0.05,
            frame_id="world",
        )
        self._status: SpatialStatus | None = None

    def _result(
        self, stage: Literal["running", "finished", "failed", "stopped"], now: float, detail: str
    ) -> None:
        assert self.active is not None
        now = self._wall_clock() if self._wall_clock else now
        self.manager.receive(
            ExecutorResult(
                executor_id=self.active.executor_id,
                action_id=self.active.action.id,
                stage=stage,
                recorded_at=now,
                clock_id=self.manager.clock_id,
                detail=detail,
            ),
            now=now,
        )

    def step(self, *, now: float) -> WorldFrame:
        if self.spatial is not None:
            self._status = self.spatial.get_status()
            if self._status.pose is not None:
                self._poses.add(self._status.pose)
            if self._status.state == "arrived":
                self.place = self._status.place_id
        for command in self.manager.take_commands():
            if command.kind == "stop":
                self.active = command
                self.stopping = True
                self.stop_at = now
                if self.spatial is not None:
                    self.spatial.cancel()
            else:
                if self.active is not None and not self.finished:
                    raise RuntimeError("adapter received concurrent actions")
                self.active = command
                self.started = now
                self.finished = False
                self.stopping = False
                self.dispatched.append(command)
                if command.executor_id == "navigation" and self.spatial is not None:
                    self.nav_request = self.spatial.go_to(command.action.destination_id).request_id
                self._result("running", now, "adapter_started")
        if self.active is not None:
            operation = self.manager.pilot.skill(self.active.action.skill_id).operation
            elapsed = now - self.started
            if self.stopping:
                base_stopped = self._base_stopped(now, after=self.stop_at)
                if self.scenario != "stop_unconfirmed" and base_stopped:
                    self._result("stopped", now, "adapter_queue_empty_and_base_stop_observed")
                    self.active = None
                    self.finished = True
                    self.stopping = False
            elif not self.finished:
                if self.scenario == "disconnect" and operation == Operation.PICK:
                    self.disconnected = True
                if (
                    self.scenario == "retention_loss"
                    and operation == Operation.NAVIGATE
                    and self.held
                    and elapsed >= self.duration_s / 2
                ):
                    self.held = None
                if (
                    self.scenario == "posture_loss"
                    and operation == Operation.NAVIGATE
                    and self.held
                    and elapsed >= self.duration_s / 2
                ):
                    self.loaded = False
                ready = elapsed >= self.duration_s
                if operation == Operation.NAVIGATE and self.spatial is not None:
                    status = self._status
                    ready = (
                        status is not None
                        and status.request_id == self.nav_request
                        and status.state == "arrived"
                        and self._base_stopped(now)
                    )
                    if (
                        status is not None
                        and status.request_id == self.nav_request
                        and status.state in {"failed", "stop_unconfirmed"}
                    ):
                        self._result("failed", now, status.reason or "navigation_failed")
                        ready = False
                if operation == Operation.OBSERVE and self.spatial is not None and ready:
                    self.last_snapshot = self.spatial.get_observation(
                        self.active.action.destination_id
                    )
                    ready = (
                        self.last_snapshot is not None
                        and self.last_snapshot.image.ts > self.started
                    )
                if self.scenario in {"timeout", "stop_unconfirmed"} and operation == Operation.PICK:
                    ready = False
                if ready:
                    self._finish_fixture(operation)
                    self.finished = True
                    self._result(
                        "finished",
                        now,
                        "navigation_finished"
                        if operation == Operation.NAVIGATE and self.spatial
                        else "artificial_executor_finished_not_sensor_verdict",
                    )
        now = self._wall_clock() if self._wall_clock else now
        frame = self._frame(now)
        self.latest_frame = frame
        self.manager.update_world(frame, now=now)
        return frame

    def _base_stopped(self, now: float, after: float = 0.0) -> bool:
        if self.spatial is not None:
            return self._poses.stopped(now, after=after)
        return (
            self.stopping
            or self.active is None
            or self.finished
            or self.active.executor_id != "navigation"
        )

    def _finish_fixture(self, operation: Operation) -> None:
        assert self.active is not None
        action = self.active.action
        if operation == Operation.NAVIGATE:
            self.place = action.destination_id
            self.aligned = ""
        elif operation == Operation.ALIGN:
            self.aligned = action.destination_id
        elif operation == Operation.PICK:
            if self.scenario == "unverified_grasp":
                self.grasp_unknown = True
            elif self.scenario != "grasp_failure":
                self.held = action.object_id
        elif operation == Operation.STOW:
            self.loaded = True
        elif operation == Operation.PLACE:
            self.placed = self.held
            self.held = None
            self.loaded = False

    def _frame(self, now: float) -> WorldFrame:
        arm: Arm = self.manager.arm
        ev = Evidence(
            origin=Origin.TEST,
            source="f4_artificial_scene",
            reference=f"fixture@{now:.9f}",
            captured_at=now,
            clock_id=self.manager.clock_id,
            frame_id="world",
        )
        base_ev = ev
        if self.spatial is not None:
            pose = self._poses.latest
            base_ev = Evidence(
                origin=Origin.SIMULATION,
                source="mujoco_ground_truth_localization",
                reference=f"odom@{pose.ts if pose else 0}",
                captured_at=pose.ts if pose else 0,
                clock_id="unix",
                frame_id="world",
            )
        observations = [
            Observation(
                key=fact("base", Predicate.STOPPED),
                value=self._base_stopped(now),
                evidence=(base_ev,),
            )
        ]
        observations.extend(
            Observation(key=fact(s, Predicate.STOPPED), value=True, evidence=(ev,))
            for s in ("elevator", "left_arm", "right_arm")
        )
        for side in ("left", "right"):
            observations.append(
                Observation(
                    key=fact("gripper", Predicate.EMPTY, arm=side),
                    value=None
                    if self.grasp_unknown and side == arm
                    else not (self.held and side == arm),
                    evidence=(ev,),
                )
            )
        for p in self.manager.pilot.places:
            observations.extend(
                (
                    Observation(
                        key=fact("base", Predicate.AT, p.id),
                        value=self.place == p.id,
                        evidence=(base_ev,),
                    ),
                    Observation(
                        key=fact("base", Predicate.ALIGNED, p.id),
                        value=self.aligned == p.id,
                        evidence=(ev,),
                    ),
                    Observation(
                        key=fact(p.id, Predicate.CLEAR),
                        value=self.scenario != "occupied",
                        evidence=(ev,),
                    ),
                )
            )
        for obj in self.manager.pilot.objects:
            source = (
                self.manager.pilot.mission.source_id
                if obj.category == self.manager.pilot.mission.object_category
                else self.manager.pilot.expansion.source_id
            )
            visible: bool | None = (
                self.place == source
                and obj.id != "bottle_02"
                and self.scenario != "absent"
                and self.held is None
                and self.placed != obj.id
            )
            if self.scenario == "ambiguous" and self.place == source:
                visible = True
            if self.scenario == "unknown":
                visible = None
            observations.extend(
                (
                    Observation(key=fact(obj.id, Predicate.VISIBLE), value=visible, evidence=(ev,)),
                    Observation(
                        key=fact(obj.id, Predicate.AT, source), value=visible, evidence=(ev,)
                    ),
                    Observation(
                        key=fact(obj.id, Predicate.HELD, arm=arm),
                        value=None if self.grasp_unknown else self.held == obj.id,
                        evidence=(ev,),
                    ),
                    Observation(
                        key=fact(obj.id, Predicate.TRANSPORT_READY, arm=arm),
                        value=self.held == obj.id and self.loaded,
                        evidence=(ev,),
                    ),
                    Observation(
                        key=fact(obj.id, Predicate.RELEASED, arm=arm),
                        value=self.placed == obj.id,
                        evidence=(ev,),
                    ),
                    Observation(
                        key=fact(
                            obj.id, Predicate.INSIDE, self.manager.pilot.mission.destination_id
                        ),
                        value=self.placed == obj.id,
                        evidence=(ev,),
                    ),
                    Observation(
                        key=fact(obj.id, Predicate.STABLE),
                        value=self.placed == obj.id,
                        evidence=(ev,),
                    ),
                )
            )
        signature = tuple(f"{o.key.model_dump_json()}:{o.value}" for o in observations)
        # Pose changes invalidate proposals even while boolean region facts stay the same.
        if self._poses.latest:
            pose = self._poses.latest
            signature += (f"{pose.x:.3f}:{pose.y:.3f}:{pose.yaw:.3f}",)
        if signature != self._signature:
            self._revision += 1
            self._signature = signature
        cameras = {name: ev for name in ("top_rgb", "active_wrist_rgb")}
        return WorldFrame(
            revision=self._revision,
            captured_at=now,
            clock_id=self.manager.clock_id,
            connected=not self.disconnected,
            observations=tuple(observations),
            cameras=cameras,
        )
