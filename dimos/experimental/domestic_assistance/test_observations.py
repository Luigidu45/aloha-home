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

from dimos.experimental.domestic_assistance.contracts import Observation, Origin
from dimos.experimental.domestic_assistance.observations import ObservationBuffer


def test_no_frame_is_not_an_empty_known_world():
    buffer = ObservationBuffer(Origin.PHYSICAL)
    with pytest.raises(ValueError, match="no sensor observation"):
        buffer.observe()


def test_late_frame_cannot_replace_newer_sensor_state():
    buffer = ObservationBuffer(Origin.PHYSICAL)
    buffer.publish(Observation(captured_at=10, origin=Origin.PHYSICAL, robot_zone="desk"))
    with pytest.raises(ValueError, match="newer"):
        buffer.publish(Observation(captured_at=9, origin=Origin.PHYSICAL, robot_zone="shelf"))
    assert buffer.observe().robot_zone == "desk"
    assert buffer.observe().captured_at == 10


def test_artificial_observation_cannot_enter_physical_buffer():
    buffer = ObservationBuffer(Origin.PHYSICAL)
    with pytest.raises(ValueError, match="origin mismatch"):
        buffer.publish(Observation(captured_at=10, origin=Origin.TEST))
