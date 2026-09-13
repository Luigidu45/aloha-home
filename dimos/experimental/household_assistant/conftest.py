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

from pathlib import Path

import pytest

from dimos.experimental.household_assistant.configuration import load_pilot
from dimos.experimental.household_assistant.contracts import ActionProposal, MissionRequest


@pytest.fixture
def pilot():
    return load_pilot(Path(__file__).parent / "configs" / "pilot.json")


@pytest.fixture
def request_a():
    return MissionRequest(
        id="request_a",
        mission_id="bring_bottle",
        instruction="Tráeme la botella al dormitorio",
        object_category="small_bottle",
        source_id="mesa_sala",
        destination_id="mesa_dormitorio",
    )


@pytest.fixture
def pickup(request_a):
    return ActionProposal(
        id="pick_a",
        request_id=request_a.id,
        skill_id="pick_bottle_from_table",
        destination_id="mesa_sala",
        object_id="bottle_01",
        arm="right",
    )
