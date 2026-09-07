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

"""Scripted baseline for exercising the same decision contract as a future VLM."""

from dimos.experimental.domestic_assistance.contracts import (
    Action,
    Decision,
    ExecutionResult,
    Mission,
    Observation,
    Outcome,
)


class ScriptedSupervisor:
    def __init__(self, actions: tuple[Action, ...]) -> None:
        self._actions = actions
        self._index = 0
        self._seen_results = 0

    def decide(
        self, mission: Mission, observation: Observation, history: tuple[ExecutionResult, ...]
    ) -> Decision:
        if len(history) > self._seen_results:
            self._seen_results = len(history)
            if history[-1].outcome == Outcome.SUCCESS:
                self._index += 1
            elif history[-1].outcome == Outcome.UNKNOWN:
                action = Action(skill="ASK", reason="Outcome has insufficient evidence")
                return Decision(candidates=(action,), selected=action, behavior="scripted-v1")
        if self._index >= len(self._actions):
            action = Action(
                skill="ABORT", reason="Script exhausted without verified mission success"
            )
        else:
            action = self._actions[self._index]
        return Decision(candidates=(action,), selected=action, behavior="scripted-v1")


def transfer_script(mission: Mission, source_zones: dict[str, str]) -> tuple[Action, ...]:
    actions: list[Action] = []
    for goal in mission.goals:
        actions.extend(
            (
                Action(skill="NAVIGATE", zone=source_zones[goal.object_id]),
                Action(skill="SEARCH", object_id=goal.object_id),
                Action(skill="PICK", object_id=goal.object_id),
                Action(skill="NAVIGATE", zone=goal.destination),
                Action(skill="PLACE", object_id=goal.object_id, zone=goal.destination),
                Action(skill="VERIFY", object_id=goal.object_id, zone=goal.destination),
            )
        )
    return tuple(actions)
