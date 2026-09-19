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

"""F4: AlohaMini1 navigation, with explicitly artificial manipulation."""

from dimos.core.coordination.blueprints import autoconnect
from dimos.core.transport import pLCMTransport
from dimos.experimental.household_assistant.mission_contracts import MissionEvent, MissionSnapshot
from dimos.experimental.household_assistant.mission_module import HouseholdMissionModule
from dimos.robot.alohamini1.blueprints.household_navigation_sim import household_navigation_sim

household_mission_sim = autoconnect(
    household_navigation_sim,
    HouseholdMissionModule.blueprint(),
).transports(
    {
        ("mission_status", MissionSnapshot): pLCMTransport.spec("/household/mission_status"),
        ("mission_event", MissionEvent): pLCMTransport.spec("/household/mission_event"),
    }
)
