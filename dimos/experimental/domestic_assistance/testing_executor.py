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
    Arm,
    EvidenceKind,
    EvidenceRef,
    ExecutionResult,
    GripperObservation,
    GripperState,
    Holder,
    NavigationState,
    ObjectObservation,
    Observation,
    Origin,
    Outcome,
    RobotObservation,
    SpatialEvidence,
    SpatialRelation,
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
        relations: dict[str, set[tuple[str, SpatialRelation]]] | None = None,
        bimanual_objects: set[str] | None = None,
    ) -> None:
        self._clock = clock
        self._locations = dict(locations)
        self._robot_zone = initial_zone
        self._held: dict[Arm, str | None] = {Arm.LEFT: None, Arm.RIGHT: None}
        self._relations = {name: set(value) for name, value in (relations or {}).items()}
        self._bimanual_objects = set(bimanual_objects or ())
        self._active: tuple[str, Action] | None = None
        self._faults = dict(faults or {})
        self._count = 0
        self.calls: list[tuple[str, str]] = []

    @property
    def origin(self) -> Origin:
        return Origin.TEST

    def observe(self) -> Observation:
        captured_at = self._clock.time()

        def evidence(identifier: str) -> EvidenceRef:
            return EvidenceRef(
                evidence_id=identifier,
                kind=EvidenceKind.TEST,
                source="deterministic-executor",
                captured_at=captured_at,
            )

        held_arms: dict[str, list[Arm]] = {}
        for arm, object_id in self._held.items():
            if object_id is not None:
                held_arms.setdefault(object_id, []).append(arm)
        return Observation(
            captured_at=captured_at,
            origin=self.origin,
            stage="deterministic-transfer",
            robot=RobotObservation(
                zone=self._robot_zone,
                base_stopped=self._active is None,
                navigation_state=(
                    NavigationState.IDLE if self._active is None else NavigationState.MOVING
                ),
                observed_at=captured_at,
                evidence=(evidence("test-robot-state"),),
            ),
            grippers=tuple(
                GripperObservation(
                    arm=arm,
                    state=(GripperState.EMPTY if object_id is None else GripperState.HOLDING),
                    object_id=object_id,
                    observed_at=captured_at,
                    evidence=(evidence(f"test-{arm.value}-gripper"),),
                )
                for arm, object_id in self._held.items()
            ),
            objects=tuple(
                ObjectObservation(
                    object_id=name,
                    zone=self._robot_zone if name in held_arms else zone,
                    held_by=(
                        Holder.BOTH
                        if len(held_arms.get(name, ())) == 2
                        else Holder(held_arms[name][0].value)
                        if name in held_arms
                        else Holder.NONE
                    ),
                    visible=zone == self._robot_zone,
                    observed_at=captured_at,
                    evidence=(evidence(f"test-object-{name}"),),
                    relations=tuple(
                        SpatialEvidence(
                            target_id=target,
                            relation=relation,
                            present=True,
                            observed_at=captured_at,
                            evidence=(evidence(f"test-relation-{name}-{target}"),),
                        )
                        for target, relation in sorted(
                            self._relations.get(name, set()), key=lambda item: item[0]
                        )
                    ),
                )
                for name, zone in self._locations.items()
            ),
        )

    def observe_after(self, captured_at: float) -> Observation | None:
        if self._clock.time() <= captured_at:
            return None
        return self.observe()

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
                failure_code=f"injected_{fault}",
                evidence=(self._execution_evidence("test-fault"),),
            )
        if action.skill == "NAVIGATE":
            assert action.zone is not None
            self._robot_zone = action.zone
            for held in self._held.values():
                if held is not None:
                    self._locations[held] = action.zone
                    self._move_dependents(held, action.zone)
        elif action.skill == "PICK":
            assert action.object_id is not None
            required = 2 if action.object_id in self._bimanual_objects else 1
            empty_arms = [arm for arm, held in self._held.items() if held is None]
            if len(empty_arms) < required:
                return ExecutionResult(
                    outcome=Outcome.FAILED,
                    detail="no empty gripper",
                    failure_code="no_empty_gripper",
                )
            for arm in empty_arms[:required]:
                self._held[arm] = action.object_id
            self._relations[action.object_id] = set()
        elif action.skill == "PLACE":
            assert (
                action.object_id is not None
                and action.zone is not None
                and action.target_id is not None
                and action.relation is not None
            )
            self._locations[action.object_id] = action.zone
            for arm, held in self._held.items():
                if held == action.object_id:
                    self._held[arm] = None
            self._relations[action.object_id] = {(action.target_id, action.relation)}
            self._move_dependents(action.object_id, action.zone)
        return ExecutionResult(
            outcome=Outcome.SUCCESS,
            detail="test executor completed",
            evidence=(self._execution_evidence("test-execution"),),
        )

    def _execution_evidence(self, evidence_id: str) -> EvidenceRef:
        return EvidenceRef(
            evidence_id=evidence_id,
            kind=EvidenceKind.TEST,
            source="deterministic-executor",
            captured_at=self._clock.time(),
        )

    def _move_dependents(self, target_id: str, zone: str) -> None:
        for object_id, relations in self._relations.items():
            if any(target == target_id for target, _ in relations):
                self._locations[object_id] = zone
                self._move_dependents(object_id, zone)

    def cancel(self, decision_id: str) -> None:
        self.calls.append(("cancel", decision_id))
        if self._faults.get(self._count) != "cancel_unconfirmed":
            self._active = None

    def is_idle(self) -> bool:
        return self._active is None
