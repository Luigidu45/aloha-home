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

from pydantic import ValidationError
import pytest

from dimos.experimental.household_assistant.assessment import assess_completion, assess_requirements
from dimos.experimental.household_assistant.configuration import PilotConfiguration
from dimos.experimental.household_assistant.contracts import (
    Evidence,
    ExecutionReport,
    ExecutionStage,
    FactKey,
    Observation,
    Origin,
    Predicate,
    Verdict,
)


@pytest.fixture
def fact():
    key = FactKey(subject_id="robot", predicate=Predicate.STOPPED)
    evidence = Evidence(
        origin=Origin.TEST,
        source="desk",
        reference="frame_1",
        captured_at=10.0,
        clock_id="desk",
        frame_id="base_link",
    )
    return Observation(key=key, value=True, evidence=(evidence,))


@pytest.mark.parametrize(
    "update,reason",
    [
        ({"origin": Origin.PHYSICAL}, "incompatible_evidence"),
        ({"clock_id": "other_clock"}, "incompatible_evidence"),
        ({"captured_at": 12.0}, "stale_or_future_evidence"),
        ({"captured_at": 1.0}, "stale_or_future_evidence"),
    ],
)
def test_incompatible_provenance_never_confirms_a_fact(fact, update, reason):
    observation = fact.model_copy(
        update={"evidence": (fact.evidence[0].model_copy(update=update),)}
    )
    result = assess_requirements(
        (fact.key,),
        (observation,),
        now=11.0,
        clock_id="desk",
        max_age_s=2.0,
        allowed_origins=frozenset({Origin.TEST}),
    )

    assert result.verdict == Verdict.UNKNOWN
    assert result.reason == reason


def test_artificial_evidence_cannot_count_as_physical_success(fact):
    result = assess_requirements(
        (fact.key,),
        (fact,),
        now=11.0,
        clock_id="desk",
        max_age_s=2.0,
        allowed_origins=frozenset({Origin.PHYSICAL}),
    )

    assert result.verdict == Verdict.UNKNOWN
    assert result.reason == "incompatible_evidence"


def test_old_fact_cannot_be_refreshed_by_adding_new_evidence(fact):
    old = fact.evidence[0].model_copy(update={"captured_at": 1.0})
    observation = fact.model_copy(update={"evidence": (old, fact.evidence[0])})
    result = assess_requirements(
        (fact.key,),
        (observation,),
        now=11.0,
        clock_id="desk",
        max_age_s=2.0,
        allowed_origins=frozenset({Origin.TEST}),
    )

    assert result.verdict == Verdict.UNKNOWN


def test_postcondition_requires_evidence_strictly_after_completion(fact):
    execution = ExecutionReport(
        action_id="act_a",
        stage=ExecutionStage.FINISHED,
        recorded_at=10.0,
        clock_id="desk",
        detail="Finished",
    )
    result = assess_completion(
        execution,
        (fact.key,),
        (fact,),
        now=11.0,
        clock_id="desk",
        max_age_s=2.0,
        allowed_origins=frozenset({Origin.TEST}),
    )

    assert result.verdict == Verdict.UNKNOWN
    assert result.reason == "evidence_not_after_completion"


def test_mixed_origins_remain_visible_in_verification(fact):
    simulated = fact.evidence[0].model_copy(
        update={"origin": Origin.SIMULATION, "source": "simulator"}
    )
    observation = fact.model_copy(update={"evidence": (fact.evidence[0], simulated)})
    result = assess_requirements(
        (fact.key,),
        (observation,),
        now=11.0,
        clock_id="desk",
        max_age_s=2.0,
        allowed_origins=frozenset({Origin.TEST, Origin.SIMULATION}),
    )

    assert result.verdict == Verdict.SUCCESS
    assert tuple(item.origin for item in result.evidence) == (Origin.TEST, Origin.SIMULATION)


def test_conflicting_observations_are_not_resolved_by_list_order(fact):
    negative = fact.model_copy(update={"value": False})
    result = assess_requirements(
        (fact.key,),
        (fact, negative),
        now=11.0,
        clock_id="desk",
        max_age_s=2.0,
        allowed_origins=frozenset({Origin.TEST}),
    )

    assert result.verdict == Verdict.UNKNOWN
    assert result.reason == "missing_or_conflicting_fact"


def test_fact_rejects_truthy_text(fact):
    raw = fact.model_dump(mode="json") | {"value": "yes"}
    with pytest.raises(ValidationError, match="valid boolean"):
        Observation.model_validate(raw)


@pytest.mark.parametrize(
    "change,error",
    [
        ("duplicate_place", "duplicate catalog identifiers"),
        ("unknown_pickup_skill", "unknown skill"),
        ("missing_executor", "executor_id"),
        ("unmeasured_delivery", "measured delivery geometry"),
    ],
)
def test_invalid_catalog_is_rejected_at_load(pilot, change, error):
    raw = pilot.model_dump(mode="json")
    if change == "duplicate_place":
        raw["places"].append(raw["places"][0])
    elif change == "unknown_pickup_skill":
        raw["mission"]["pickup_skill_id"] = "invented"
    elif change == "missing_executor":
        del raw["skills"][0]["executor_id"]
    else:
        raw["places"][1]["accessibility_confirmed"] = True
    with pytest.raises(ValidationError, match=error):
        PilotConfiguration.model_validate(raw)


def test_action_cannot_change_the_users_object_selection(pilot, request_a, pickup):
    request = request_a.model_copy(update={"selected_object_id": "bottle_02"})
    with pytest.raises(ValueError, match="differs from user selection"):
        pilot.validate_action(request, pickup, available_executor_ids={"act_pick_table"})


def test_request_cannot_switch_the_floor_mission_to_table_pickup(pilot, request_a):
    request = request_a.model_copy(
        update={"mission_id": "recover_remote", "object_category": "remote_control"}
    )
    with pytest.raises(ValueError, match="outside the configured mission"):
        pilot.validate_request(request)


def test_manipulation_requires_a_named_arm(pilot, request_a, pickup):
    action = pickup.model_copy(update={"arm": None})
    with pytest.raises(ValueError, match="explicit arm"):
        pilot.validate_action(request_a, action, available_executor_ids={"act_pick_table"})


def test_no_precondition_can_be_verified_vacuously():
    with pytest.raises(ValueError, match="nonempty and unique"):
        assess_requirements(
            (),
            (),
            now=11.0,
            clock_id="desk",
            max_age_s=2.0,
            allowed_origins=frozenset({Origin.TEST}),
        )
