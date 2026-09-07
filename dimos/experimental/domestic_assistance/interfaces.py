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

"""Local interfaces; physical implementations must use bounded, nonblocking calls."""

from typing import Protocol

from dimos.experimental.domestic_assistance.contracts import (
    Action,
    Decision,
    ExecutionResult,
    Mission,
    Observation,
    Origin,
)


class Executor(Protocol):
    @property
    def origin(self) -> Origin: ...

    def start(self, decision_id: str, action: Action) -> None:
        """Accept one action; must not wait for physical completion."""
        ...

    def poll(self, decision_id: str) -> ExecutionResult | None:
        """Return completion, or None while running; never infer grasp from motor completion."""
        ...

    def cancel(self, decision_id: str) -> None:
        """Request stop. Acknowledging this call does not establish that the robot stopped."""
        ...

    def is_idle(self) -> bool:
        """True only when no action is executing and the controlled actuators have stopped."""
        ...


class Observer(Protocol):
    def observe(self) -> Observation: ...


class Supervisor(Protocol):
    def decide(
        self, mission: Mission, observation: Observation, history: tuple[ExecutionResult, ...]
    ) -> Decision:
        """Return candidates without invoking tools. Model backends need bounded inference."""
        ...


class Clock(Protocol):
    def monotonic(self) -> float: ...
    def time(self) -> float: ...
