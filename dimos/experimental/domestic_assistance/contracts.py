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

"""Versioned semantic contracts, independent of robot drivers and model backends."""

from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1, pattern=r"^[a-zA-Z0-9_.-]+$")]
Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Sha256 = Annotated[str, Field(pattern=r"^[a-fA-F0-9]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Origin(str, Enum):
    TEST = "test"
    SIMULATION = "simulation"
    PHYSICAL = "physical"


class Outcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"


class DispatchStatus(str, Enum):
    EXECUTED = "EXECUTED"
    REJECTED_PRECONDITION = "REJECTED_PRECONDITION"
    DISPATCH_FAILED = "DISPATCH_FAILED"
    TERMINAL_CONTROL = "TERMINAL_CONTROL"
    CANCELLED_BEFORE_DISPATCH = "CANCELLED_BEFORE_DISPATCH"


class Arm(str, Enum):
    LEFT = "left"
    RIGHT = "right"


class Holder(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"
    NONE = "none"


class GripperState(str, Enum):
    EMPTY = "EMPTY"
    HOLDING = "HOLDING"
    UNKNOWN = "UNKNOWN"


class NavigationState(str, Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    ARRIVED = "ARRIVED"
    UNKNOWN = "UNKNOWN"


class SpatialRelation(str, Enum):
    IN = "IN"
    ON = "ON"
    AT = "AT"
    NEAR = "NEAR"


class EvidenceKind(str, Enum):
    SENSOR = "sensor"
    EXECUTOR = "executor"
    VERIFIER = "verifier"
    OPERATOR = "operator"
    TEST = "test"


class EvidenceRef(Contract):
    """A typed, timestamped reference supporting an observed or reported fact."""

    evidence_id: Identifier
    kind: EvidenceKind
    source: Identifier
    captured_at: Seconds
    uri: Annotated[str, Field(min_length=1)] | None = None
    sha256: Sha256 | None = None
    detail: str = ""

    @model_validator(mode="after")
    def hash_requires_uri(self) -> Self:
        if self.sha256 is not None and self.uri is None:
            raise ValueError("evidence sha256 requires a uri")
        return self


class Action(Contract):
    """Closed semantic vocabulary; no arbitrary executor commands or extra arguments."""

    skill: Literal["NAVIGATE", "SEARCH", "VERIFY", "PICK", "PLACE", "ASK", "ABORT"]
    object_id: Identifier | None = None
    zone: Identifier | None = None
    target_id: Identifier | None = None
    relation: SpatialRelation | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_arguments(self) -> Self:
        required = {
            "NAVIGATE": {"zone"},
            "SEARCH": {"object_id"},
            "VERIFY": {"object_id", "zone", "target_id", "relation"},
            "PICK": {"object_id"},
            "PLACE": {"object_id", "zone", "target_id", "relation"},
            "ASK": {"reason"},
            "ABORT": {"reason"},
        }[self.skill]
        supplied = {
            name
            for name in ("object_id", "zone", "target_id", "relation", "reason")
            if getattr(self, name) is not None
        }
        if supplied != required:
            raise ValueError(f"{self.skill} requires exactly {sorted(required)}")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("reason must not be blank")
        return self


class PlacementTarget(Contract):
    zone: Identifier
    target_id: Identifier
    relation: SpatialRelation


class Goal(Contract):
    object_id: Identifier
    destination: PlacementTarget
    manipulation_mode: Literal["single_arm", "bimanual"] = "single_arm"


class MissionTarget(Contract):
    target_id: Identifier
    kind: Literal["basket", "tray", "surface", "container", "landmark"]


class Mission(Contract):
    task_id: Identifier
    instruction: Annotated[str, Field(min_length=1)]
    zones: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    targets: tuple[MissionTarget, ...] = ()
    goals: Annotated[tuple[Goal, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_goals(self) -> Self:
        if len(set(self.zones)) != len(self.zones):
            raise ValueError("zones must be unique")
        if len({target.target_id for target in self.targets}) != len(self.targets):
            raise ValueError("targets must be unique")
        if len({goal.object_id for goal in self.goals}) != len(self.goals):
            raise ValueError("each object must have exactly one goal")
        target_ids = {target.target_id for target in self.targets}
        if any(goal.destination.zone not in self.zones for goal in self.goals):
            raise ValueError("goal destination zone is not registered")
        if any(goal.destination.target_id not in target_ids for goal in self.goals):
            raise ValueError("goal destination target is not registered")
        return self

    def validate_action(self, action: Action) -> None:
        if action.zone is not None and action.zone not in self.zones:
            raise ValueError("action references an unregistered zone")
        if action.object_id is not None and action.object_id not in {
            goal.object_id for goal in self.goals
        }:
            raise ValueError("action references an unregistered object")
        if action.target_id is not None and action.target_id not in {
            target.target_id for target in self.targets
        }:
            raise ValueError("action references an unregistered target")


class Keyframe(Contract):
    keyframe_id: Identifier
    path: Annotated[str, Field(min_length=1)]
    camera: Identifier
    captured_at: Seconds
    sha256: Sha256 | None = None


class SpatialEvidence(Contract):
    target_id: Identifier
    relation: SpatialRelation
    present: bool
    observed_at: Seconds
    evidence: Annotated[tuple[EvidenceRef, ...], Field(min_length=1)]


class ObjectObservation(Contract):
    object_id: Identifier
    zone: Identifier | None = None
    visible: bool | None = None
    held_by: Holder | None = None
    observed_at: Seconds
    evidence: tuple[EvidenceRef, ...] = ()
    relations: tuple[SpatialEvidence, ...] = ()

    @model_validator(mode="after")
    def known_facts_require_evidence(self) -> Self:
        if (
            self.zone is not None or self.visible is not None or self.held_by is not None
        ) and not self.evidence:
            raise ValueError("known object facts require evidence")
        if any(relation.observed_at > self.observed_at for relation in self.relations):
            raise ValueError("object relation is newer than the object observation")
        return self

    def relation(self, target_id: str, relation: SpatialRelation) -> SpatialEvidence | None:
        return next(
            (
                item
                for item in self.relations
                if item.target_id == target_id and item.relation == relation
            ),
            None,
        )


class RobotObservation(Contract):
    zone: Identifier | None
    base_stopped: bool | None
    navigation_state: NavigationState = NavigationState.UNKNOWN
    observed_at: Seconds
    evidence: tuple[EvidenceRef, ...] = ()

    @model_validator(mode="after")
    def known_facts_require_evidence(self) -> Self:
        if (self.zone is not None or self.base_stopped is not None) and not self.evidence:
            raise ValueError("known robot facts require evidence")
        return self


class GripperObservation(Contract):
    arm: Arm
    state: GripperState
    object_id: Identifier | None = None
    observed_at: Seconds
    evidence: tuple[EvidenceRef, ...] = ()

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.state == GripperState.HOLDING and self.object_id is None:
            raise ValueError("a holding gripper must identify its object")
        if self.state != GripperState.HOLDING and self.object_id is not None:
            raise ValueError("only a holding gripper may identify an object")
        if self.state != GripperState.UNKNOWN and not self.evidence:
            raise ValueError("known gripper state requires evidence")
        return self


class Observation(Contract):
    """Only information available before choosing the next action; no terminal label."""

    captured_at: Seconds
    origin: Origin
    stage: Identifier | None = None
    robot: RobotObservation
    grippers: Annotated[tuple[GripperObservation, ...], Field(min_length=2, max_length=2)]
    objects: tuple[ObjectObservation, ...] = ()
    keyframes: tuple[Keyframe, ...] = ()

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if len({obj.object_id for obj in self.objects}) != len(self.objects):
            raise ValueError("duplicate object observations")
        if {gripper.arm for gripper in self.grippers} != {Arm.LEFT, Arm.RIGHT}:
            raise ValueError("snapshot must contain exactly the left and right grippers")
        timestamps = [
            self.robot.observed_at,
            *(gripper.observed_at for gripper in self.grippers),
            *(obj.observed_at for obj in self.objects),
            *(frame.captured_at for frame in self.keyframes),
        ]
        if any(timestamp > self.captured_at for timestamp in timestamps):
            raise ValueError("snapshot contains a fact from the future")

        held_objects: dict[Arm, str] = {}
        for obj in self.objects:
            arms: tuple[Arm, ...] = ()
            if obj.held_by in {Holder.LEFT, Holder.RIGHT}:
                arms = (Arm(obj.held_by.value),)
            elif obj.held_by == Holder.BOTH:
                arms = (Arm.LEFT, Arm.RIGHT)
            for arm in arms:
                if arm in held_objects:
                    raise ValueError("one gripper cannot hold multiple objects")
                held_objects[arm] = obj.object_id
        for gripper in self.grippers:
            held = held_objects.get(gripper.arm)
            if gripper.state == GripperState.HOLDING and held != gripper.object_id:
                raise ValueError("gripper and object holding facts contradict")
            if gripper.state == GripperState.EMPTY and held is not None:
                raise ValueError("empty gripper contradicts held object")
        return self

    @property
    def robot_zone(self) -> str | None:
        return self.robot.zone

    @property
    def base_stopped(self) -> bool | None:
        return self.robot.base_stopped

    def object(self, object_id: str | None) -> ObjectObservation | None:
        return next((obj for obj in self.objects if obj.object_id == object_id), None)

    def gripper(self, arm: Arm) -> GripperObservation:
        return next(gripper for gripper in self.grippers if gripper.arm == arm)


class ExecutionResult(Contract):
    """Executor completion, distinct from verification of its semantic effect."""

    outcome: Outcome
    detail: str
    failure_code: Identifier | None = None
    evidence: tuple[EvidenceRef, ...] = ()


class VerificationResult(Contract):
    """Semantic interpretation of executor completion and post-action evidence."""

    outcome: Outcome
    predicate: Identifier
    detail: str
    evidence: tuple[EvidenceRef, ...] = ()


class Candidate(Contract):
    action: Action
    generation_rank: Annotated[int, Field(ge=0)]
    log_probability: float | None = None
    q_value: Probability | None = None


class BehaviorMetadata(Contract):
    policy: Identifier
    method: Literal["M0", "M1", "M2", "M3", "M4", "scripted"]
    exploratory: bool = False
    seed: int | None = None


class Decision(Contract):
    candidates: Annotated[tuple[Candidate, ...], Field(min_length=1, max_length=3)]
    selected: Action
    behavior: BehaviorMetadata

    @model_validator(mode="after")
    def selected_is_candidate(self) -> Self:
        if self.selected not in {candidate.action for candidate in self.candidates}:
            raise ValueError("selected action must occur in candidates")
        if len({candidate.generation_rank for candidate in self.candidates}) != len(
            self.candidates
        ):
            raise ValueError("candidate generation ranks must be unique")
        return self


class CandidateAssessment(Contract):
    action: Action
    eligible: bool
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> Self:
        if self.eligible == (self.rejection_reason is not None):
            raise ValueError("only an ineligible candidate has a rejection reason")
        return self


class HistoryEntry(Contract):
    decision_id: Identifier
    action: Action
    dispatch_status: DispatchStatus
    executor_result: ExecutionResult | None
    executor_completed_at: Seconds | None = None
    verification_result: VerificationResult
    duration_s: Seconds

    @model_validator(mode="after")
    def completion_time_matches_execution(self) -> Self:
        if (self.executor_result is None) != (self.executor_completed_at is None):
            raise ValueError("executor result and completion timestamp must occur together")
        if self.dispatch_status == DispatchStatus.EXECUTED and self.executor_result is None:
            raise ValueError("executed dispatch requires an executor result")
        if self.dispatch_status != DispatchStatus.EXECUTED and self.executor_result is not None:
            raise ValueError("non-executed dispatch cannot contain an executor result")
        return self


class AttemptRecord(Contract):
    action: Action
    consecutive_attempts: Annotated[int, Field(gt=0)]


class DecisionContext(Contract):
    observation: Observation
    history: tuple[HistoryEntry, ...] = ()
    attempts: tuple[AttemptRecord, ...] = ()


class Limits(Contract):
    max_decisions: Annotated[int, Field(gt=0)] = 20
    max_consecutive_attempts: Annotated[int, Field(gt=0)] = 2
    mission_timeout_s: Annotated[float, Field(gt=0)] = 480.0
    skill_timeout_s: Annotated[float, Field(gt=0)] = 30.0
    verification_timeout_s: Annotated[float, Field(gt=0)] = 3.0
    cancellation_timeout_s: Annotated[float, Field(gt=0)] = 5.0
    max_observation_age_s: Annotated[float, Field(gt=0)] = 2.0
    max_fact_age_s: Annotated[float, Field(gt=0)] = 2.0


class ComponentManifest(Contract):
    name: Identifier
    version: Annotated[str, Field(min_length=1)]
    sha256: Sha256 | None = None


class ExperimentManifest(Contract):
    experiment_id: Identifier
    method: Literal["M0", "M1", "M2", "M3", "M4", "software-test"]
    code: ComponentManifest
    supervisor: ComponentManifest
    executor: ComponentManifest
    verifier: ComponentManifest
    mission_config_sha256: Sha256 | None = None
    scenario_config_sha256: Sha256 | None = None
    prompt_sha256: Sha256 | None = None
    code_dirty: bool = False


class RunMetadata(Contract):
    episode_id: Identifier
    scenario_id: Identifier
    session_id: Identifier
    split_group: Identifier
    seed: int
    origin: Origin
    manifest: ExperimentManifest


class InitialPlacement(Contract):
    object_id: Identifier
    zone: Identifier
    target_id: Identifier | None = None
    relation: SpatialRelation | None = None

    @model_validator(mode="after")
    def validate_relation(self) -> Self:
        if (self.target_id is None) != (self.relation is None):
            raise ValueError("initial target and relation must be supplied together")
        return self


class Perturbation(Contract):
    perturbation_id: Identifier
    kind: Literal[
        "OBJECT_MOVED",
        "OBJECT_HIDDEN",
        "EMPTY_GRASP",
        "DESTINATION_OCCUPIED",
        "NAVIGATION_TIMEOUT",
        "DISTRACTOR",
    ]
    trigger: Annotated[str, Field(min_length=1)]
    detail: Annotated[str, Field(min_length=1)]


class Scenario(Contract):
    scenario_id: Identifier
    task_id: Identifier
    split_group: Identifier
    initial_robot_zone: Identifier
    initial_placements: Annotated[tuple[InitialPlacement, ...], Field(min_length=1)]
    perturbations: tuple[Perturbation, ...] = ()
    reset_checklist: Annotated[tuple[str, ...], Field(min_length=1)]
    nominal_actions: Annotated[tuple[Action, ...], Field(min_length=1)]

    def validate_mission(self, mission: Mission) -> None:
        if self.task_id != mission.task_id:
            raise ValueError("scenario task does not match mission")
        if self.initial_robot_zone not in mission.zones:
            raise ValueError("initial robot zone is not registered")
        object_ids = {goal.object_id for goal in mission.goals}
        target_ids = {target.target_id for target in mission.targets}
        for placement in self.initial_placements:
            if placement.zone not in mission.zones:
                raise ValueError("initial placement zone is not registered")
            if placement.object_id not in object_ids:
                raise ValueError("initial placement object is not registered")
            if placement.target_id is not None and placement.target_id not in target_ids:
                raise ValueError("initial placement target is not registered")
        for action in self.nominal_actions:
            mission.validate_action(action)


class Intervention(Contract):
    kind: Literal["VERBAL", "REMOTE_CONTROL", "PHYSICAL", "EMERGENCY_STOP", "OTHER"]
    occurred_at: Seconds
    duration_s: Seconds = 0.0
    detail: Annotated[str, Field(min_length=1)]
    evidence: tuple[EvidenceRef, ...] = ()


class EpisodeSummary(Contract):
    reason: Literal[
        "SUCCESS",
        "ABORT",
        "ASK",
        "CANCELLED",
        "MISSION_TIMEOUT",
        "DECISION_LIMIT",
        "RETRY_LIMIT",
        "INVALID_DECISION",
        "STALE_OBSERVATION",
        "ERROR",
        "CANCEL_UNCONFIRMED",
    ]
    mission_success: bool
    autonomous_success: bool
    assistance_requested: bool = False
    intervention_count: Annotated[int, Field(ge=0)] = 0
    intervention_duration_s: Seconds = 0.0
    experiment_valid: bool = True
    exclusion_reason: str | None = None
    decisions: Annotated[int, Field(ge=0)]
    duration_s: Seconds
    detail: str = ""

    @model_validator(mode="after")
    def validate_success(self) -> Self:
        if self.mission_success != (self.reason == "SUCCESS"):
            raise ValueError("mission success label contradicts termination reason")
        assisted = self.assistance_requested or self.intervention_count > 0
        if self.autonomous_success != (self.mission_success and not assisted):
            raise ValueError("autonomous success contradicts mission result or assistance")
        if self.experiment_valid == (self.exclusion_reason is not None):
            raise ValueError("only an invalid experiment has an exclusion reason")
        return self
