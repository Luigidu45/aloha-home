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
    Decision,
    EpisodeSummary,
    Mission,
    Observation,
)


@pytest.mark.parametrize(
    "payload",
    [
        {"skill": "move_so101_joints", "positions": [1, 2]},
        {"skill": "NAVIGATE"},
        {"skill": "PICK", "object_id": "book", "zone": "shelf"},
        {"skill": "ASK", "reason": " "},
        {"skill": "PLACE", "object_id": "book", "zone": "../../external"},
        {"skill": "NAVIGATE", "zone": "desk", "code": "arbitrary()"},
    ],
)
def test_rejects_nonsemantic_actions_and_wrong_arguments(payload):
    with pytest.raises(ValidationError):
        Action.model_validate_json(json.dumps(payload))


def test_cannot_select_an_action_missing_from_candidates():
    with pytest.raises(ValidationError, match="selected action"):
        Decision(
            candidates=(Action(skill="NAVIGATE", zone="shelf"),),
            selected=Action(skill="NAVIGATE", zone="desk"),
            behavior="test",
        )


def test_terminal_label_cannot_enter_model_observation():
    with pytest.raises(ValidationError, match="Extra inputs"):
        Observation.model_validate_json(
            '{"captured_at": 5, "origin": "test", "mission_success": true}'
        )


def test_future_keyframe_is_rejected():
    with pytest.raises(ValidationError, match="future"):
        Observation.model_validate_json(
            json.dumps(
                {
                    "captured_at": 5,
                    "origin": "test",
                    "keyframes": [{"path": "frame.jpg", "camera": "top", "captured_at": 6}],
                }
            )
        )


def test_goal_must_reference_registered_zone():
    with pytest.raises(ValidationError, match="destination"):
        Mission.model_validate_json(
            json.dumps(
                {
                    "task_id": "reading",
                    "instruction": "Bring book",
                    "zones": ["desk"],
                    "goals": [{"object_id": "book", "destination": "elsewhere"}],
                }
            )
        )


def test_assisted_episode_cannot_be_autonomous_success():
    with pytest.raises(ValidationError, match="assisted"):
        EpisodeSummary(
            reason="SUCCESS",
            autonomous_success=True,
            assistance_requested=True,
            decisions=1,
            duration_s=1,
        )
