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

import pytest

from dimos.experimental.household_assistant.assessment import (
    assess_completion,
    assess_requirements,
    resolve_target,
)
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
def evidence():
    return Evidence(
        origin=Origin.TEST,
        source="desk_case",
        reference="synthetic_frame_1",
        captured_at=10.0,
        clock_id="desk",
        frame_id="camera_optical",
    )


@pytest.fixture
def visibility(evidence):
    return (
        Observation(
            key=FactKey(subject_id="bottle_01", predicate=Predicate.VISIBLE),
            value=True,
            evidence=(evidence,),
        ),
        Observation(
            key=FactKey(subject_id="bottle_02", predicate=Predicate.VISIBLE),
            value=False,
            evidence=(evidence,),
        ),
    )


@pytest.fixture
def timing():
    return {
        "now": 11.0,
        "clock_id": "desk",
        "max_age_s": 2.0,
        "allowed_origins": frozenset({Origin.TEST}),
    }


@pytest.fixture
def finished():
    return ExecutionReport(
        action_id="pick_a",
        stage=ExecutionStage.FINISHED,
        recorded_at=9.0,
        clock_id="desk",
        detail="Motor command finished",
    )


def test_c01_known_request_and_single_visible_target(pilot, request_a, pickup, visibility, timing):
    result = resolve_target(pilot, request_a, visibility, **timing)
    skill = pilot.validate_action(request_a, pickup, available_executor_ids={"act_pick_table"})

    assert result.status == "selected"
    assert result.candidates == ("bottle_01",)
    assert skill.id == "pick_bottle_from_table"
    assert skill.implementation == "planned"


def test_c02_unknown_delivery_is_rejected(pilot, request_a):
    request = request_a.model_copy(update={"destination_id": "unknown_room"})
    with pytest.raises(ValueError, match="unknown delivery region"):
        pilot.validate_request(request)


def test_c03_skill_without_available_executor_is_rejected(pilot, request_a, pickup):
    with pytest.raises(ValueError, match="no available executor"):
        pilot.validate_action(request_a, pickup, available_executor_ids=set())


def test_c04_invented_skill_is_rejected(pilot, request_a, pickup):
    action = pickup.model_copy(update={"skill_id": "open_refrigerator"})
    with pytest.raises(ValueError, match="unknown skill"):
        pilot.validate_action(request_a, action, available_executor_ids={"act_pick_table"})


def test_c05_observed_absence_does_not_select_a_target(pilot, request_a, visibility, timing):
    observations = tuple(item.model_copy(update={"value": False}) for item in visibility)
    result = resolve_target(pilot, request_a, observations, **timing)

    assert result.status == "not_found"
    assert result.candidates == ()


def test_c06_two_visible_candidates_require_user_selection(pilot, request_a, visibility, timing):
    observations = tuple(item.model_copy(update={"value": True}) for item in visibility)
    ambiguous = resolve_target(pilot, request_a, observations, **timing)
    clarified_request = request_a.model_copy(update={"selected_object_id": "bottle_02"})
    clarified = resolve_target(pilot, clarified_request, observations, **timing)

    assert ambiguous.status == "ambiguous"
    assert ambiguous.candidates == ("bottle_01", "bottle_02")
    assert clarified.status == "selected"
    assert clarified.candidates == ("bottle_02",)


def test_c07_old_image_cannot_confirm_a_current_target(pilot, request_a, visibility, timing):
    result = resolve_target(pilot, request_a, visibility, **(timing | {"now": 20.0}))

    assert result.status == "unknown"
    assert result.candidates == ()


def test_c08_finished_motors_do_not_prove_an_uncertain_grasp(finished, evidence, timing):
    key = FactKey(subject_id="bottle_01", predicate=Predicate.HELD, arm="right")
    observation = Observation(key=key, value=None, evidence=(evidence,))
    result = assess_completion(finished, (key,), (observation,), **timing)

    assert result.verdict == Verdict.UNKNOWN
    assert result.reason == "inconclusive_fact"


def test_c09_cancel_request_is_not_finished_execution(finished, evidence, timing):
    cancelling = finished.model_copy(update={"stage": ExecutionStage.CANCEL_REQUESTED})
    key = FactKey(subject_id="robot", predicate=Predicate.STOPPED)
    observation = Observation(key=key, value=True, evidence=(evidence,))
    result = assess_completion(cancelling, (key,), (observation,), **timing)

    assert result.verdict == Verdict.UNKNOWN
    assert result.reason == "execution_not_finished"


def test_c10_being_in_the_room_does_not_prove_accessible_delivery(finished, evidence, timing):
    inside = FactKey(subject_id="bottle_01", predicate=Predicate.INSIDE, place_id="mesa_dormitorio")
    released = FactKey(subject_id="bottle_01", predicate=Predicate.RELEASED, arm="right")
    observations = (
        Observation(key=inside, value=False, evidence=(evidence,)),
        Observation(key=released, value=True, evidence=(evidence,)),
    )
    result = assess_completion(finished, (inside, released), observations, **timing)

    assert result.verdict == Verdict.FAILURE
    assert result.reason == "requirement_false"


def test_loaded_home_alone_does_not_allow_transport_after_object_loss(evidence, timing):
    posture = FactKey(subject_id="robot", predicate=Predicate.TRANSPORT_READY, arm="right")
    held = FactKey(subject_id="bottle_01", predicate=Predicate.HELD, arm="right")
    observations = (
        Observation(key=posture, value=True, evidence=(evidence,)),
        Observation(key=held, value=False, evidence=(evidence,)),
    )
    result = assess_requirements((posture, held), observations, **timing)

    assert result.verdict == Verdict.FAILURE


def test_floor_expansion_requires_its_own_pickup_skill(pilot, request_a, pickup):
    request = request_a.model_copy(
        update={
            "mission_id": "recover_remote",
            "object_category": "remote_control",
            "source_id": "suelo_sala",
        }
    )
    wrong = pickup.model_copy(update={"destination_id": "suelo_sala", "object_id": "remote_01"})
    with pytest.raises(ValueError, match="outside declared skill domain"):
        pilot.validate_action(request, wrong, available_executor_ids={"act_pick_table"})
    correct = wrong.model_copy(update={"skill_id": "pick_remote_from_floor"})
    skill = pilot.validate_action(request, correct, available_executor_ids={"act_pick_floor"})

    assert skill.id == pilot.expansion.pickup_skill_id
