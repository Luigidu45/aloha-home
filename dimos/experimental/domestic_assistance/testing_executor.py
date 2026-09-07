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

"""Deterministic software exercise, not a physics simulator or real-world dataset."""

from typing import Literal

from dimos.experimental.domestic_assistance.contracts import (
    Action,
    ExecutionResult,
    ObjectObservation,
    Observation,
    Origin,
    Outcome,
)
from dimos.experimental.domestic_assistance.interfaces import Clock

Fault = Literal["failed", "unknown", "timeout", "cancel_unconfirmed"]


class ManualClock:
    def __init__(self, epoch: float = 1_800_000_000.0) -> None:
        self._epoch = epoch
        self._elapsed = 0.0

    def monotonic(self) -> float:
        return self._elapsed

    def time(self) -> float:
        return self._epoch + self._elapsed

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("time cannot move backwards")
        self._elapsed += seconds


class DeterministicExecutor:
    """Models semantic effects solely to exercise the lifecycle and journal contracts."""

    def __init__(
        self,
        clock: Clock,
        locations: dict[str, str],
        initial_zone: str,
        faults: dict[int, Fault] | None = None,
    ) -> None:
        self._clock = clock
        self._locations = dict(locations)
        self._robot_zone = initial_zone
        self._held: str | None = None
        self._active: tuple[str, Action] | None = None
        self._faults = dict(faults or {})
        self._count = 0
        self.calls: list[tuple[str, str]] = []

    @property
    def origin(self) -> Origin:
        return Origin.TEST

    def observe(self) -> Observation:
        return Observation(
            captured_at=self._clock.time(),
            origin=self.origin,
            robot_zone=self._robot_zone,
            base_stopped=self._active is None,
            grippers_empty=self._held is None,
            objects=tuple(
                ObjectObservation(
                    object_id=name,
                    zone=self._robot_zone if self._held == name else zone,
                    held=self._held == name,
                    visible=zone == self._robot_zone,
                    observed_at=self._clock.time(),
                    evidence=(f"test-state:{name}",),
                )
                for name, zone in self._locations.items()
            ),
        )

    def start(self, decision_id: str, action: Action) -> None:
        if self._active is not None:
            raise RuntimeError("another action is active")
        self._active = (decision_id, action)
        self._count += 1
        self.calls.append(("start", decision_id))

    def poll(self, decision_id: str) -> ExecutionResult | None:
        if self._active is None or self._active[0] != decision_id:
            raise ValueError("unknown active decision")
        fault = self._faults.get(self._count)
        if fault in {"timeout", "cancel_unconfirmed"}:
            return None
        _, action = self._active
        self._active = None
        if fault in {"failed", "unknown"}:
            return ExecutionResult(
                outcome=Outcome.FAILED if fault == "failed" else Outcome.UNKNOWN,
                detail=f"injected {fault}",
                evidence=("test-fault",),
            )
        if action.skill == "NAVIGATE":
            assert action.zone is not None
            self._robot_zone = action.zone
        elif action.skill == "PICK":
            self._held = action.object_id
        elif action.skill == "PLACE":
            assert action.object_id is not None and action.zone is not None
            self._locations[action.object_id] = action.zone
            self._held = None
        return ExecutionResult(
            outcome=Outcome.SUCCESS, detail="test executor completed", evidence=("test-state",)
        )

    def cancel(self, decision_id: str) -> None:
        self.calls.append(("cancel", decision_id))
        if self._faults.get(self._count) != "cancel_unconfirmed":
            self._active = None

    def is_idle(self) -> bool:
        return self._active is None
