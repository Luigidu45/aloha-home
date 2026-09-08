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

"""Conservative semantic checks over timestamped, observable facts."""

import hashlib
import json
from typing import Any

from dimos.experimental.domestic_assistance.contracts import (
    Action,
    Arm,
    ComponentManifest,
    ExecutionResult,
    GripperState,
    Holder,
    Mission,
    Observation,
    Outcome,
    VerificationResult,
)
from dimos.experimental.domestic_assistance.interfaces import Verifier

_OBSERVED_FACTS_V2_POLICY = {
    "name": "observed-facts",
    "version": "observed-facts-v2",
    "preconditions": {
        "manipulation_requires_fresh_stopped_base": True,
        "pick_requires_visible_colocated_unheld_object": True,
        "pick_requires_fresh_empty_grippers": True,
        "place_requires_consistent_held_object": True,
    },
    "postconditions": {
        "require_newer_snapshot": True,
        "navigate": "fresh_arrival_and_stop",
        "search": "fresh_positive_or_negative_visibility",
        "pick": "fresh_object_and_gripper_holding_agreement",
        "place_verify": "fresh_positive_relation_and_release",
        "mission": "all_goals_freshly_satisfied_and_base_stopped",
    },
}


def _policy_fingerprint(policy: dict[str, Any]) -> str:
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _fresh(observed_at: float, state: Observation, max_fact_age_s: float) -> bool:
    age = state.captured_at - observed_at
    return 0 <= age <= max_fact_age_s


class ObservedFactsVerifier:
    """Fixed verification policy shared by all experimental methods in a campaign."""

    name = "observed-facts"
    version = "observed-facts-v2"
    fingerprint = _policy_fingerprint(_OBSERVED_FACTS_V2_POLICY)

    def precondition_error(
        self,
        mission: Mission,
        action: Action,
        state: Observation,
        max_fact_age_s: float,
    ) -> str | None:
        robot_fresh = _fresh(state.robot.observed_at, state, max_fact_age_s)
        if action.skill in {"PICK", "PLACE"} and (
            not robot_fresh or state.base_stopped is not True
        ):
            return "base must be freshly observed stopped before manipulation"

        obj = state.object(action.object_id)
        if action.skill == "PICK":
            if (
                obj is None
                or not _fresh(obj.observed_at, state, max_fact_age_s)
                or obj.visible is not True
                or state.robot_zone is None
                or obj.zone != state.robot_zone
            ):
                return "target must be freshly observed at the robot's current zone"
            if obj.held_by != Holder.NONE:
                return "target holding state must be known and not held"
            empty_grippers = [
                gripper
                for gripper in state.grippers
                if (
                    gripper.state == GripperState.EMPTY
                    and _fresh(gripper.observed_at, state, max_fact_age_s)
                )
            ]
            mode = next(
                goal.manipulation_mode
                for goal in mission.goals
                if goal.object_id == action.object_id
            )
            required_grippers = 2 if mode == "bimanual" else 1
            if len(empty_grippers) < required_grippers:
                return f"{required_grippers} gripper(s) must be freshly observed empty"

        if action.skill == "PLACE":
            if (
                obj is None
                or not _fresh(obj.observed_at, state, max_fact_age_s)
                or obj.held_by not in {Holder.LEFT, Holder.RIGHT, Holder.BOTH}
                or state.robot_zone != action.zone
            ):
                return "target must be freshly observed held at the requested destination zone"
            mode = next(
                goal.manipulation_mode
                for goal in mission.goals
                if goal.object_id == action.object_id
            )
            if mode == "bimanual" and obj.held_by != Holder.BOTH:
                return "bimanual object must be observed held by both grippers"
            expected_arms = (
                (Arm.LEFT, Arm.RIGHT) if obj.held_by == Holder.BOTH else (Arm(obj.held_by.value),)
            )
            if any(
                not _fresh(state.gripper(arm).observed_at, state, max_fact_age_s)
                or state.gripper(arm).state != GripperState.HOLDING
                or state.gripper(arm).object_id != action.object_id
                for arm in expected_arms
            ):
                return "holding object and gripper evidence are inconsistent or stale"
        return None

    def verify_action(
        self,
        mission: Mission,
        action: Action,
        before: Observation,
        after: Observation,
        result: ExecutionResult,
        max_fact_age_s: float,
    ) -> VerificationResult:
        if result.outcome != Outcome.SUCCESS:
            return VerificationResult(
                outcome=result.outcome,
                predicate="executor_completion",
                detail=result.detail,
                evidence=result.evidence,
            )
        if after.captured_at <= before.captured_at:
            return VerificationResult(
                outcome=Outcome.UNKNOWN,
                predicate="post_action_observation",
                detail="post-action snapshot is not newer than the decision snapshot",
                evidence=result.evidence,
            )

        if action.skill == "NAVIGATE":
            robot = after.robot
            evidence = (*result.evidence, *robot.evidence)
            verified = (
                robot.zone == action.zone
                and robot.base_stopped is True
                and robot.observed_at > before.captured_at
                and _fresh(robot.observed_at, after, max_fact_age_s)
                and bool(robot.evidence)
            )
            return VerificationResult(
                outcome=Outcome.SUCCESS if verified else Outcome.UNKNOWN,
                predicate="arrived_and_stopped",
                detail=(
                    result.detail
                    if verified
                    else "navigation completion lacks fresh arrival and stop evidence"
                ),
                evidence=evidence,
            )

        obj = after.object(action.object_id)
        if (
            obj is None
            or obj.observed_at <= before.captured_at
            or not _fresh(obj.observed_at, after, max_fact_age_s)
            or not obj.evidence
        ):
            return VerificationResult(
                outcome=Outcome.UNKNOWN,
                predicate="object_postcondition",
                detail="executor completed but fresh object evidence is unavailable",
                evidence=result.evidence,
            )
        evidence = (*result.evidence, *obj.evidence)

        if action.skill == "SEARCH":
            if obj.visible is None:
                outcome = Outcome.UNKNOWN
                predicate = "search_inconclusive"
            else:
                outcome = Outcome.SUCCESS
                predicate = "search_found" if obj.visible else "search_not_found"
            return VerificationResult(
                outcome=outcome,
                predicate=predicate,
                detail=result.detail,
                evidence=evidence,
            )

        if action.skill == "PICK":
            mode = next(
                goal.manipulation_mode
                for goal in mission.goals
                if goal.object_id == action.object_id
            )
            holder = obj.held_by
            if holder not in {Holder.LEFT, Holder.RIGHT, Holder.BOTH}:
                return VerificationResult(
                    outcome=Outcome.UNKNOWN,
                    predicate="object_held",
                    detail="grasp completion lacks fresh held-object evidence",
                    evidence=evidence,
                )
            expected_arms: tuple[Arm, ...]
            if holder == Holder.BOTH:
                expected_arms = (Arm.LEFT, Arm.RIGHT)
            else:
                expected_arms = (Arm(holder.value),)
            verified = (mode != "bimanual" or holder == Holder.BOTH) and all(
                after.gripper(arm).state == GripperState.HOLDING
                and after.gripper(arm).object_id == action.object_id
                and after.gripper(arm).observed_at > before.captured_at
                and _fresh(after.gripper(arm).observed_at, after, max_fact_age_s)
                for arm in expected_arms
            )
            gripper_evidence = tuple(
                evidence for arm in expected_arms for evidence in after.gripper(arm).evidence
            )
            return VerificationResult(
                outcome=Outcome.SUCCESS if verified else Outcome.UNKNOWN,
                predicate="object_held",
                detail=result.detail if verified else "held-object and gripper evidence disagree",
                evidence=(*evidence, *gripper_evidence),
            )

        if action.skill in {"PLACE", "VERIFY"}:
            assert action.target_id is not None and action.relation is not None
            relation = obj.relation(action.target_id, action.relation)
            if (
                relation is None
                or relation.observed_at <= before.captured_at
                or not _fresh(relation.observed_at, after, max_fact_age_s)
            ):
                return VerificationResult(
                    outcome=Outcome.UNKNOWN,
                    predicate="placement_relation",
                    detail="placement relation lacks fresh positive or negative evidence",
                    evidence=evidence,
                )
            relation_evidence = (*evidence, *relation.evidence)
            if not relation.present:
                return VerificationResult(
                    outcome=Outcome.FAILED,
                    predicate="placement_relation_violated",
                    detail="fresh evidence shows that the requested relation is false",
                    evidence=relation_evidence,
                )
            released = obj.held_by == Holder.NONE
            return VerificationResult(
                outcome=Outcome.SUCCESS if released else Outcome.UNKNOWN,
                predicate="placement_relation_satisfied",
                detail=(
                    result.detail
                    if released
                    else "relation is visible but release state is unknown"
                ),
                evidence=relation_evidence,
            )

        return VerificationResult(
            outcome=Outcome.UNKNOWN,
            predicate="unsupported_verification",
            detail="action has no semantic verification rule",
            evidence=result.evidence,
        )

    def mission_complete(self, mission: Mission, state: Observation, max_fact_age_s: float) -> bool:
        if state.base_stopped is not True or not _fresh(
            state.robot.observed_at, state, max_fact_age_s
        ):
            return False
        for goal in mission.goals:
            obj = state.object(goal.object_id)
            if (
                obj is None
                or obj.held_by != Holder.NONE
                or not _fresh(obj.observed_at, state, max_fact_age_s)
            ):
                return False
            destination = goal.destination
            relation = obj.relation(destination.target_id, destination.relation)
            if (
                obj.zone != destination.zone
                or relation is None
                or not relation.present
                or not _fresh(relation.observed_at, state, max_fact_age_s)
            ):
                return False
        return True


DEFAULT_VERIFIER = ObservedFactsVerifier()


class VerifierRegistry:
    """Resolve frozen verifier implementations recorded by episode manifests."""

    def __init__(self, verifiers: tuple[Verifier, ...] = ()) -> None:
        self._verifiers: dict[tuple[str, str], Verifier] = {}
        for verifier in verifiers:
            self.register(verifier)

    def register(self, verifier: Verifier) -> None:
        key = (verifier.name, verifier.version)
        if key in self._verifiers:
            raise ValueError(f"verifier is already registered: {key}")
        self._verifiers[key] = verifier

    def resolve(self, component: ComponentManifest) -> Verifier:
        key = (component.name, component.version)
        try:
            verifier = self._verifiers[key]
        except KeyError as exc:
            raise ValueError(f"verifier is not registered: {key}") from exc
        if component.sha256 is not None and component.sha256.lower() != verifier.fingerprint:
            raise ValueError(f"verifier fingerprint does not match registry: {key}")
        return verifier


DEFAULT_VERIFIER_REGISTRY = VerifierRegistry((DEFAULT_VERIFIER,))


def precondition_error(
    mission: Mission, action: Action, state: Observation, max_fact_age_s: float = 2.0
) -> str | None:
    return DEFAULT_VERIFIER.precondition_error(mission, action, state, max_fact_age_s)


def verify_action(
    mission: Mission,
    action: Action,
    before: Observation,
    after: Observation,
    result: ExecutionResult,
    max_fact_age_s: float = 2.0,
) -> VerificationResult:
    return DEFAULT_VERIFIER.verify_action(mission, action, before, after, result, max_fact_age_s)


def mission_complete(mission: Mission, state: Observation, max_fact_age_s: float = 2.0) -> bool:
    return DEFAULT_VERIFIER.mission_complete(mission, state, max_fact_age_s)
