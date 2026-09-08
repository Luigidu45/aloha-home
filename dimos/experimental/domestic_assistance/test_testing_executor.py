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

from dimos.experimental.domestic_assistance.contracts import (
    Action,
    GripperState,
    Holder,
    Outcome,
)
from dimos.experimental.domestic_assistance.testing_executor import (
    DeterministicExecutor,
    ManualClock,
)


def test_bimanual_object_occupies_both_grippers():
    clock = ManualClock()
    executor = DeterministicExecutor(
        clock,
        locations={"tray": "storage"},
        initial_zone="storage",
        bimanual_objects={"tray"},
    )
    executor.start("decision-0001", Action(skill="PICK", object_id="tray"))
    result = executor.poll("decision-0001")
    clock.advance(0.1)
    observation = executor.observe()
    tray = observation.object("tray")
    assert result is not None and result.outcome == Outcome.SUCCESS
    assert tray is not None and tray.held_by == Holder.BOTH
    assert {gripper.state for gripper in observation.grippers} == {GripperState.HOLDING}
    assert {gripper.object_id for gripper in observation.grippers} == {"tray"}
