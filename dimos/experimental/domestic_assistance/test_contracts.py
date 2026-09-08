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

import json

from pydantic import ValidationError
import pytest

from dimos.experimental.domestic_assistance.contracts import (
    Action,
    Arm,
    BehaviorMetadata,
    Candidate,
    Decision,
    EpisodeSummary,
    EvidenceKind,
    EvidenceRef,
    GripperObservation,
    GripperState,
    Holder,
    Mission,
    ObjectObservation,
    Observation,
    Origin,
    RobotObservation,
)


def evidence(captured_at=5):
    return EvidenceRef(
        evidence_id="evidence",
        kind=EvidenceKind.TEST,
        source="test",
        captured_at=captured_at,
    )


def observation(captured_at=5):
    item = evidence(captured_at)
    return Observation(
        captured_at=captured_at,
        origin=Origin.TEST,
        robot=RobotObservation(
            zone="desk",
            base_stopped=True,
            observed_at=captured_at,
            evidence=(item,),
        ),
        grippers=(
            GripperObservation(
                arm=Arm.LEFT,
                state=GripperState.EMPTY,
                observed_at=captured_at,
                evidence=(item,),
            ),
            GripperObservation(
                arm=Arm.RIGHT,
                state=GripperState.EMPTY,
                observed_at=captured_at,
                evidence=(item,),
            ),
        ),
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"skill": "move_so101_joints", "positions": [1, 2]},
        {"skill": "NAVIGATE"},
        {"skill": "PICK", "object_id": "book", "zone": "shelf"},
        {"skill": "ASK", "reason": " "},
        {
            "skill": "PLACE",
            "object_id": "book",
            "zone": "../../external",
            "target_id": "desk",
            "relation": "ON",
        },
        {"skill": "NAVIGATE", "zone": "desk", "code": "arbitrary()"},
    ],
)
def test_rejects_nonsemantic_actions_and_wrong_arguments(payload):
    with pytest.raises(ValidationError):
        Action.model_validate_json(json.dumps(payload))


def test_cannot_select_an_action_missing_from_candidates():
    with pytest.raises(ValidationError, match="selected action"):
        Decision(
            candidates=(
                Candidate(action=Action(skill="NAVIGATE", zone="shelf"), generation_rank=0),
            ),
            selected=Action(skill="NAVIGATE", zone="desk"),
            behavior=BehaviorMetadata(policy="test", method="scripted"),
        )


def test_terminal_label_cannot_enter_model_observation():
    with pytest.raises(ValidationError, match="Extra inputs"):
        Observation.model_validate({**observation().model_dump(), "mission_success": True})


def test_future_keyframe_is_rejected():
    with pytest.raises(ValidationError, match="future"):
        Observation.model_validate(
            {
                **observation().model_dump(),
                "keyframes": [
                    {
                        "keyframe_id": "frame-1",
                        "path": "frame.jpg",
                        "camera": "top",
                        "captured_at": 6,
                    }
                ],
            }
        )


def test_goal_must_reference_registered_zone():
    with pytest.raises(ValidationError, match="destination"):
        Mission.model_validate_json(
            json.dumps(
                {
                    "task_id": "reading",
                    "instruction": "Bring book",
                    "zones": ["desk"],
                    "targets": [{"target_id": "spot", "kind": "surface"}],
                    "goals": [
                        {
                            "object_id": "book",
                            "destination": {
                                "zone": "elsewhere",
                                "target_id": "spot",
                                "relation": "ON",
                            },
                        }
                    ],
                }
            )
        )


def test_assisted_episode_cannot_be_autonomous_success():
    with pytest.raises(ValidationError, match="assistance"):
        EpisodeSummary(
            reason="SUCCESS",
            mission_success=True,
            autonomous_success=True,
            assistance_requested=True,
            decisions=1,
            duration_s=1,
        )


def test_known_object_fact_requires_evidence():
    with pytest.raises(ValidationError, match="require evidence"):
        ObjectObservation(
            object_id="book",
            zone="desk",
            visible=True,
            held_by=Holder.NONE,
            observed_at=5,
        )


def test_bimanual_snapshot_rejects_holding_contradiction():
    current = observation()
    held = ObjectObservation(
        object_id="book",
        zone="desk",
        visible=True,
        held_by=Holder.LEFT,
        observed_at=5,
        evidence=(evidence(),),
    )
    with pytest.raises(ValidationError, match="contradict"):
        Observation.model_validate({**current.model_dump(), "objects": [held.model_dump()]})
