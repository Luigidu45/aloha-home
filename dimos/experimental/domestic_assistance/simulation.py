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

"""DimOS navigation and evidence adapters for domestic-assistance simulation.

Manipulation in this phase is deliberately symbolic. It exercises the same semantic
contracts and lifecycle as a future ACT adapter without claiming physics or policy
performance.
"""

from collections import deque
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from threading import RLock
from typing import Annotated, Literal

from pydantic import Field, model_validator

from dimos.experimental.domestic_assistance.contracts import (
    Action,
    Arm,
    Contract,
    EvidenceKind,
    EvidenceRef,
    ExecutionResult,
    GripperObservation,
    GripperState,
    Holder,
    Identifier,
    Keyframe,
    Mission,
    NavigationState,
    ObjectObservation,
    Observation,
    Origin,
    Outcome,
    RobotObservation,
    Scenario,
    Sha256,
    SpatialEvidence,
    SpatialRelation,
)
from dimos.experimental.domestic_assistance.interfaces import Clock
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.sensor_msgs.Image import Image
from dimos.navigation.base import NavigationState as DimosNavigationState
from dimos.navigation.navigation_spec import NavigationInterfaceSpec


class ZonePose(Contract):
    """Map-specific navigation pose and semantic membership tolerance."""

    zone: Identifier
    frame_id: Identifier = "world"
    x: float
    y: float
    yaw: float = 0.0
    position_tolerance_m: Annotated[float, Field(gt=0)] = 0.55
    yaw_tolerance_rad: Annotated[float, Field(gt=0, le=math.pi)] = math.pi

    def to_pose_stamped(self, captured_at: float) -> PoseStamped:
        half_yaw = self.yaw / 2.0
        return PoseStamped(
            ts=captured_at,
            frame_id=self.frame_id,
            position=[self.x, self.y, 0.0],
            orientation=[0.0, 0.0, math.sin(half_yaw), math.cos(half_yaw)],
        )


class SimulationZoneMap(Contract):
    """Coordinates kept separate from the semantic mission configuration."""

    config_schema_version: Literal[1] = 1
    task_id: Identifier
    map_id: Identifier
    zones: Annotated[tuple[ZonePose, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_zones(self) -> "SimulationZoneMap":
        if len({item.zone for item in self.zones}) != len(self.zones):
            raise ValueError("simulation zones must be unique")
        return self

    def validate_mission(self, mission: Mission) -> None:
        if self.config_schema_version != mission.config_schema_version:
            raise ValueError("mission and simulation map schema versions do not match")
        if self.task_id != mission.task_id:
            raise ValueError("simulation map task does not match mission")
        configured = {item.zone for item in self.zones}
        expected = set(mission.zones)
        if configured != expected:
            raise ValueError(
                "simulation map zones do not exactly match mission zones: "
                f"missing={sorted(expected - configured)}, extra={sorted(configured - expected)}"
            )

    def pose_for(self, zone: str) -> ZonePose:
        try:
            return next(item for item in self.zones if item.zone == zone)
        except StopIteration as exc:
            raise ValueError(f"zone has no simulation pose: {zone}") from exc

    def resolve(self, pose: PoseStamped) -> str | None:
        """Resolve a pose only when it is inside exactly one configured zone."""
        matches = [
            item.zone
            for item in self.zones
            if item.frame_id == pose.frame_id
            and math.hypot(item.x - pose.x, item.y - pose.y) <= item.position_tolerance_m
            and _angular_distance(item.yaw, pose.yaw) <= item.yaw_tolerance_rad
        ]
        return matches[0] if len(matches) == 1 else None


class SimulationZoneBundle(Contract):
    zone_map: SimulationZoneMap
    config_sha256: Sha256


def load_simulation_zone_map(path: Path, mission: Mission) -> SimulationZoneBundle:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid simulation map JSON: {path}") from exc
    zone_map = SimulationZoneMap.model_validate(payload)
    zone_map.validate_mission(mission)
    return SimulationZoneBundle(
        zone_map=zone_map,
        config_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _angular_distance(first: float, second: float) -> float:
    return abs((first - second + math.pi) % (2 * math.pi) - math.pi)


class DimosNavigationAdapter:
    """Translate semantic zones to the nonblocking DimOS navigation Spec."""

    def __init__(
        self,
        navigation: NavigationInterfaceSpec,
        zone_map: SimulationZoneMap,
        clock: Clock,
    ) -> None:
        self._navigation = navigation
        self._zone_map = zone_map
        self._clock = clock
        self._active: tuple[str, str] | None = None
        self._cancelling = False
        self._dispatched = False

    def start(self, decision_id: str, zone: str) -> None:
        if self._active is not None:
            raise RuntimeError("navigation action is already active")
        self._active = (decision_id, zone)
        self._cancelling = False
        self._dispatched = False
        self._try_dispatch()

    def poll(self, decision_id: str) -> ExecutionResult | None:
        _, zone = self._require_active(decision_id)
        if not self._dispatched:
            if self._navigation.is_goal_reached():
                self._active = None
                return ExecutionResult(
                    outcome=Outcome.SUCCESS,
                    detail=f"DimOS reached simulation zone {zone}",
                    evidence=(self._evidence(decision_id, "navigation-complete"),),
                )
            self._try_dispatch()
            if not self._dispatched:
                return None
        state = self._navigation.get_state()
        if state in {DimosNavigationState.FOLLOWING_PATH, DimosNavigationState.RECOVERY}:
            return None
        if state != DimosNavigationState.IDLE:
            return None
        reached = self._navigation.is_goal_reached()
        if reached:
            self._active = None
            self._cancelling = False
            self._dispatched = False
            return ExecutionResult(
                outcome=Outcome.SUCCESS,
                detail=f"DimOS reached simulation zone {zone}",
                evidence=(self._evidence(decision_id, "navigation-complete"),),
            )
        # The current NavigationInterfaceSpec has no terminal-failure or map-ready
        # signal. IDLE may be a brief replanning transition, so only the runner's
        # bounded skill timeout may turn this ambiguous state into a failure.
        return None

    def cancel(self, decision_id: str) -> None:
        self._require_active(decision_id)
        # set_goal() may install a goal before raising while the costmap is not
        # ready, so cancellation must always reach the backend after any attempt.
        self._cancelling = True
        self._navigation.cancel_goal()

    def is_idle(self) -> bool:
        state_idle = self._navigation.get_state() == DimosNavigationState.IDLE
        if self._active is None:
            return state_idle
        if self._cancelling and state_idle:
            self._active = None
            self._cancelling = False
            self._dispatched = False
            return True
        return False

    def _require_active(self, decision_id: str) -> tuple[str, str]:
        if self._active is None or self._active[0] != decision_id:
            raise ValueError("unknown active navigation decision")
        return self._active

    def _try_dispatch(self) -> None:
        assert self._active is not None
        _, zone = self._active
        goal = self._zone_map.pose_for(zone).to_pose_stamped(self._clock.time())
        try:
            accepted = self._navigation.set_goal(goal)
        except Exception as exc:
            if "No current global costmap available" in str(exc):
                return
            raise
        if not accepted:
            raise RuntimeError("DimOS navigation rejected the goal")
        self._dispatched = True

    def _evidence(self, decision_id: str, suffix: str) -> EvidenceRef:
        return EvidenceRef(
            evidence_id=f"{decision_id}-{suffix}",
            kind=EvidenceKind.EXECUTOR,
            source="dimos-navigation-simulation",
            captured_at=self._clock.time(),
        )


class SymbolicSimulationWorld:
    """Thread-safe semantic state; not a manipulation or perception simulator."""

    def __init__(self, mission: Mission, scenario: Scenario) -> None:
        scenario.validate_mission(mission)
        self._lock = RLock()
        self._locations = {
            placement.object_id: placement.zone for placement in scenario.initial_placements
        }
        self._relations = {
            placement.object_id: (
                {(placement.target_id, placement.relation)}
                if placement.target_id is not None and placement.relation is not None
                else set()
            )
            for placement in scenario.initial_placements
        }
        self._held: dict[Arm, str | None] = {Arm.LEFT: None, Arm.RIGHT: None}
        self._bimanual = {
            goal.object_id for goal in mission.goals if goal.manipulation_mode == "bimanual"
        }

    def apply(self, action: Action, robot_zone: str | None) -> None:
        """Apply only abstract SEARCH/PICK/PLACE/VERIFY effects."""
        with self._lock:
            if action.skill in {"SEARCH", "VERIFY"}:
                return
            if action.skill == "PICK":
                assert action.object_id is not None
                required = 2 if action.object_id in self._bimanual else 1
                empty = [arm for arm, value in self._held.items() if value is None]
                if len(empty) < required:
                    raise RuntimeError("symbolic simulator has insufficient empty grippers")
                for arm in empty[:required]:
                    self._held[arm] = action.object_id
                self._relations[action.object_id] = set()
                if robot_zone is not None:
                    self._locations[action.object_id] = robot_zone
                return
            if action.skill == "PLACE":
                assert (
                    action.object_id is not None
                    and action.zone is not None
                    and action.target_id is not None
                    and action.relation is not None
                )
                self._locations[action.object_id] = action.zone
                for arm, value in self._held.items():
                    if value == action.object_id:
                        self._held[arm] = None
                self._relations[action.object_id] = {(action.target_id, action.relation)}
                self._move_dependents(action.object_id, action.zone)

    def facts(
        self, robot_zone: str | None
    ) -> tuple[
        dict[str, str],
        dict[str, Holder],
        dict[Arm, str | None],
        dict[str, set[tuple[str, SpatialRelation]]],
    ]:
        with self._lock:
            locations = dict(self._locations)
            held_arms: dict[str, list[Arm]] = {}
            for arm, object_id in self._held.items():
                if object_id is not None:
                    held_arms.setdefault(object_id, []).append(arm)
                    if robot_zone is not None:
                        locations[object_id] = robot_zone
                        self._move_dependent_locations(
                            object_id, robot_zone, locations, self._relations
                        )
            holders = {
                object_id: (
                    Holder.BOTH
                    if len(held_arms.get(object_id, ())) == 2
                    else Holder(held_arms[object_id][0].value)
                    if object_id in held_arms
                    else Holder.NONE
                )
                for object_id in locations
            }
            return (
                locations,
                holders,
                dict(self._held),
                {name: set(items) for name, items in self._relations.items()},
            )

    @classmethod
    def _move_dependent_locations(
        cls,
        target_id: str,
        zone: str,
        locations: dict[str, str],
        relations: dict[str, set[tuple[str, SpatialRelation]]],
    ) -> None:
        for object_id, object_relations in relations.items():
            if any(target == target_id for target, _ in object_relations):
                locations[object_id] = zone
                cls._move_dependent_locations(object_id, zone, locations, relations)

    def _move_dependents(self, target_id: str, zone: str) -> None:
        for object_id, relations in self._relations.items():
            if any(target == target_id for target, _ in relations):
                self._locations[object_id] = zone
                self._move_dependents(object_id, zone)


class SimulationExecutor:
    """One-action arbiter combining real DimOS navigation with symbolic skills."""

    def __init__(
        self,
        navigation: DimosNavigationAdapter,
        world: SymbolicSimulationWorld,
        observer: "SimulationObserver",
        clock: Clock,
    ) -> None:
        self._navigation = navigation
        self._world = world
        self._observer = observer
        self._clock = clock
        self._active: tuple[str, Action] | None = None
        self._cancelling_navigation = False
        self._navigation_result: ExecutionResult | None = None

    @property
    def origin(self) -> Origin:
        return Origin.SIMULATION

    def start(self, decision_id: str, action: Action) -> None:
        if self._active is not None or not self._navigation.is_idle():
            raise RuntimeError("simulation executor is not idle")
        if action.skill not in {"NAVIGATE", "SEARCH", "PICK", "PLACE", "VERIFY"}:
            raise ValueError(f"unsupported executable action: {action.skill}")
        self._active = (decision_id, action)
        self._cancelling_navigation = False
        self._navigation_result = None
        if action.skill == "NAVIGATE":
            assert action.zone is not None
            if self._observer.navigation_complete(action.zone):
                self._navigation_result = ExecutionResult(
                    outcome=Outcome.SUCCESS,
                    detail=f"robot was already stopped in simulation zone {action.zone}",
                    evidence=(
                        EvidenceRef(
                            evidence_id=f"{decision_id}-navigation-noop",
                            kind=EvidenceKind.EXECUTOR,
                            source="dimos-navigation-simulation",
                            captured_at=self._clock.time(),
                        ),
                    ),
                )
            else:
                self._navigation.start(decision_id, action.zone)

    def poll(self, decision_id: str) -> ExecutionResult | None:
        action = self._require_active(decision_id)
        if action.skill == "NAVIGATE":
            result = self._navigation_result
            if result is None:
                result = self._navigation.poll(decision_id)
                self._navigation_result = result
            if result is None:
                return None
            if result.outcome != Outcome.SUCCESS or self._observer.navigation_complete(action.zone):
                self._active = None
                self._navigation_result = None
                return result
            return None
        self._world.apply(action, self._observer.robot_zone)
        self._active = None
        return ExecutionResult(
            outcome=Outcome.SUCCESS,
            detail=f"symbolic simulation completed {action.skill}",
            evidence=(
                EvidenceRef(
                    evidence_id=f"{decision_id}-symbolic-completion",
                    kind=EvidenceKind.EXECUTOR,
                    source="symbolic-manipulation-simulation",
                    captured_at=self._clock.time(),
                    detail="No manipulation dynamics or ACT policy were executed.",
                ),
            ),
        )

    def cancel(self, decision_id: str) -> None:
        action = self._require_active(decision_id)
        if action.skill == "NAVIGATE":
            if self._navigation_result is None:
                self._cancelling_navigation = True
                self._navigation.cancel(decision_id)
            else:
                self._active = None
                self._navigation_result = None
        else:
            self._active = None

    def is_idle(self) -> bool:
        if self._active is None:
            return self._navigation.is_idle()
        if self._cancelling_navigation and self._navigation.is_idle():
            self._active = None
            self._cancelling_navigation = False
            return True
        return False

    def _require_active(self, decision_id: str) -> Action:
        if self._active is None or self._active[0] != decision_id:
            raise ValueError("unknown active simulation decision")
        return self._active[1]


@dataclass(frozen=True)
class _PoseSample:
    timestamp: float
    x: float
    y: float
    yaw: float


class SimulationObserver:
    """Fuse odometry, planner state and images into auditable simulation snapshots."""

    def __init__(
        self,
        navigation: NavigationInterfaceSpec,
        zone_map: SimulationZoneMap,
        world: SymbolicSimulationWorld,
        evidence_directory: Path,
        *,
        required_cameras: tuple[str, ...] = ("front_camera",),
        max_sensor_skew_s: float = 0.75,
        stable_pose_samples: int = 3,
        stopped_position_delta_m: float = 0.015,
        stopped_yaw_delta_rad: float = 0.02,
    ) -> None:
        if not required_cameras:
            raise ValueError("at least one camera is required")
        if stable_pose_samples < 2:
            raise ValueError("stable_pose_samples must be at least two")
        self._navigation = navigation
        self._zone_map = zone_map
        self._world = world
        self._evidence_directory = evidence_directory
        self._required_cameras = required_cameras
        self._max_sensor_skew_s = max_sensor_skew_s
        self._stopped_position_delta_m = stopped_position_delta_m
        self._stopped_yaw_delta_rad = stopped_yaw_delta_rad
        self._stable_pose_samples = stable_pose_samples
        self._poses: deque[_PoseSample] = deque(maxlen=stable_pose_samples)
        self._latest_pose: PoseStamped | None = None
        self._images: dict[str, Image] = {}
        self._keyframe_cache: dict[tuple[str, float], Keyframe] = {}
        self._lock = RLock()

    @property
    def robot_zone(self) -> str | None:
        with self._lock:
            return self._zone_map.resolve(self._latest_pose) if self._latest_pose else None

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._snapshot_timestamp() is not None

    def navigation_complete(self, expected_zone: str | None) -> bool:
        """Require pose-derived arrival and several stable odometry samples."""
        with self._lock:
            return (
                expected_zone is not None
                and self._latest_pose is not None
                and self._zone_map.resolve(self._latest_pose) == expected_zone
                and self._base_stopped(self._navigation.get_state()) is True
            )

    def update_odom(self, pose: PoseStamped) -> None:
        with self._lock:
            if self._latest_pose is not None and pose.ts <= self._latest_pose.ts:
                return
            self._latest_pose = pose
            self._poses.append(_PoseSample(pose.ts, pose.x, pose.y, pose.yaw))

    def update_camera(self, camera: str, image: Image) -> None:
        if camera not in self._required_cameras:
            return
        with self._lock:
            previous = self._images.get(camera)
            if previous is None or image.ts > previous.ts:
                self._images[camera] = image

    def observe(self) -> Observation:
        with self._lock:
            captured_at = self._snapshot_timestamp()
            if captured_at is None:
                raise ValueError("simulation sensors are incomplete or unsynchronized")
            return self._build_observation(captured_at)

    def observe_after(self, captured_at: float) -> Observation | None:
        with self._lock:
            snapshot_at = self._snapshot_timestamp()
            if (
                snapshot_at is None
                or self._latest_pose is None
                or self._latest_pose.ts <= captured_at
                or any(self._images[camera].ts <= captured_at for camera in self._required_cameras)
            ):
                return None
            return self._build_observation(snapshot_at)

    def _snapshot_timestamp(self) -> float | None:
        if self._latest_pose is None or any(
            camera not in self._images for camera in self._required_cameras
        ):
            return None
        timestamps = [
            self._latest_pose.ts,
            *(self._images[camera].ts for camera in self._required_cameras),
        ]
        if max(timestamps) - min(timestamps) > self._max_sensor_skew_s:
            return None
        return max(timestamps)

    def _build_observation(self, captured_at: float) -> Observation:
        assert self._latest_pose is not None
        robot_zone = self._zone_map.resolve(self._latest_pose)
        nav_state = self._navigation.get_state()
        stopped = self._base_stopped(nav_state)
        keyframes = tuple(
            self._keyframe(camera, self._images[camera]) for camera in self._required_cameras
        )
        odom_evidence = EvidenceRef(
            evidence_id=f"sim-odom-{round(self._latest_pose.ts * 1_000_000)}",
            kind=EvidenceKind.SENSOR,
            source="mujoco-odometry",
            captured_at=self._latest_pose.ts,
            detail="Base stop is inferred from planner state and consecutive poses.",
        )
        symbolic_evidence = EvidenceRef(
            evidence_id=f"sim-symbolic-{round(captured_at * 1_000_000)}",
            kind=EvidenceKind.SENSOR,
            source="symbolic-simulation-state",
            captured_at=captured_at,
            detail="Ground-truth task state; not a vision prediction.",
        )
        locations, holders, grippers, relations = self._world.facts(robot_zone)
        return Observation(
            captured_at=captured_at,
            origin=Origin.SIMULATION,
            stage="dimos-mujoco-symbolic-manipulation",
            robot=RobotObservation(
                zone=robot_zone,
                base_stopped=stopped,
                navigation_state=self._contract_navigation_state(nav_state, stopped),
                observed_at=self._latest_pose.ts,
                evidence=(odom_evidence,),
            ),
            grippers=tuple(
                GripperObservation(
                    arm=arm,
                    state=GripperState.EMPTY if object_id is None else GripperState.HOLDING,
                    object_id=object_id,
                    observed_at=captured_at,
                    evidence=(symbolic_evidence,),
                )
                for arm, object_id in grippers.items()
            ),
            objects=tuple(
                ObjectObservation(
                    object_id=object_id,
                    zone=zone,
                    visible=(holders[object_id] != Holder.NONE or zone == robot_zone),
                    held_by=holders[object_id],
                    observed_at=captured_at,
                    evidence=(symbolic_evidence,),
                    relations=tuple(
                        SpatialEvidence(
                            target_id=target,
                            relation=relation,
                            present=True,
                            observed_at=captured_at,
                            evidence=(symbolic_evidence,),
                        )
                        for target, relation in sorted(
                            relations.get(object_id, set()), key=lambda item: item[0]
                        )
                    ),
                )
                for object_id, zone in locations.items()
            ),
            keyframes=keyframes,
        )

    def _base_stopped(self, state: DimosNavigationState) -> bool | None:
        if state != DimosNavigationState.IDLE:
            return False
        if len(self._poses) < self._stable_pose_samples:
            return None
        reference = self._poses[-1]
        stable = all(
            math.hypot(sample.x - reference.x, sample.y - reference.y)
            <= self._stopped_position_delta_m
            and _angular_distance(sample.yaw, reference.yaw) <= self._stopped_yaw_delta_rad
            for sample in self._poses
        )
        return stable

    @staticmethod
    def _contract_navigation_state(
        state: DimosNavigationState, stopped: bool | None
    ) -> NavigationState:
        if state in {DimosNavigationState.FOLLOWING_PATH, DimosNavigationState.RECOVERY}:
            return NavigationState.MOVING
        if state == DimosNavigationState.IDLE and stopped is True:
            return NavigationState.IDLE
        return NavigationState.UNKNOWN

    def _keyframe(self, camera: str, image: Image) -> Keyframe:
        cache_key = (camera, image.ts)
        cached = self._keyframe_cache.get(cache_key)
        if cached is not None:
            return cached
        self._evidence_directory.mkdir(parents=True, exist_ok=True)
        timestamp_us = round(image.ts * 1_000_000)
        path = (self._evidence_directory / f"{camera}-{timestamp_us}.jpg").resolve()
        if not image.save(str(path)):
            raise OSError(f"failed to write simulation keyframe: {path}")
        frame = Keyframe(
            keyframe_id=f"sim-{camera}-{timestamp_us}",
            path=str(path),
            camera=camera,
            captured_at=image.ts,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        self._keyframe_cache[cache_key] = frame
        return frame
