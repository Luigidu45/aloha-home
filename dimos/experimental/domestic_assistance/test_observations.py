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

from dimos.experimental.domestic_assistance.contracts import (
    Arm,
    EvidenceKind,
    EvidenceRef,
    GripperObservation,
    GripperState,
    Observation,
    Origin,
    RobotObservation,
)
from dimos.experimental.domestic_assistance.observations import ObservationBuffer


def snapshot(captured_at, origin, zone="desk"):
    evidence = EvidenceRef(
        evidence_id="sensor-state",
        kind=EvidenceKind.SENSOR,
        source="test-sensor",
        captured_at=captured_at,
    )
    return Observation(
        captured_at=captured_at,
        origin=origin,
        robot=RobotObservation(
            zone=zone,
            base_stopped=True,
            observed_at=captured_at,
            evidence=(evidence,),
        ),
        grippers=tuple(
            GripperObservation(
                arm=arm,
                state=GripperState.EMPTY,
                observed_at=captured_at,
                evidence=(evidence,),
            )
            for arm in (Arm.LEFT, Arm.RIGHT)
        ),
    )


def test_no_frame_is_not_an_empty_known_world():
    buffer = ObservationBuffer(Origin.PHYSICAL)
    with pytest.raises(ValueError, match="no sensor observation"):
        buffer.observe()


def test_late_frame_cannot_replace_newer_sensor_state():
    buffer = ObservationBuffer(Origin.PHYSICAL)
    buffer.publish(snapshot(10, Origin.PHYSICAL))
    with pytest.raises(ValueError, match="newer"):
        buffer.publish(snapshot(9, Origin.PHYSICAL, "shelf"))
    assert buffer.observe().robot_zone == "desk"
    assert buffer.observe().captured_at == 10


def test_artificial_observation_cannot_enter_physical_buffer():
    buffer = ObservationBuffer(Origin.PHYSICAL)
    with pytest.raises(ValueError, match="origin mismatch"):
        buffer.publish(snapshot(10, Origin.TEST))


def test_observe_after_never_returns_the_same_snapshot():
    buffer = ObservationBuffer(Origin.PHYSICAL)
    buffer.publish(snapshot(10, Origin.PHYSICAL))
    assert buffer.observe_after(10) is None
    buffer.publish(snapshot(11, Origin.PHYSICAL, "shelf"))
    assert buffer.observe_after(10) == snapshot(11, Origin.PHYSICAL, "shelf")
