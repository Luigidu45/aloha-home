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

import math

import numpy as np
import pytest

from dimos.core.global_config import GlobalConfig
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Quaternion import Quaternion
from dimos.msgs.geometry_msgs.Vector3 import Vector3
from dimos.navigation.replanning_a_star.controllers import HolonomicController


@pytest.mark.parametrize("yaw, expected", [(0.0, (0.0, 0.5)), (math.pi / 2, (0.5, 0.0))])
def test_holonomic_path_velocity_is_body_relative_and_speed_limited(yaw, expected):
    controller = HolonomicController(GlobalConfig(), speed=0.5, control_frequency=10)
    pose = PoseStamped(
        position=Vector3(1.0, 2.0, 0.0),
        orientation=Quaternion(0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2)),
    )
    command = controller.advance(np.array([1.0, 4.0]), pose)
    assert (command.linear.x, command.linear.y) == pytest.approx(expected, abs=1e-12)
    assert command.angular.z == 0.0


def test_holonomic_arrival_slows_below_old_minimum_speed_and_stops_at_goal():
    controller = HolonomicController(GlobalConfig(), speed=0.5, control_frequency=10)
    pose = PoseStamped(position=Vector3(0.0, 0.0, 0.0))
    near = controller.advance(np.array([0.03, 0.04]), pose)
    assert (near.linear.x, near.linear.y) == pytest.approx((0.03, 0.04))
    stopped = controller.advance(np.array([0.0, 0.0]), pose)
    assert (stopped.linear.x, stopped.linear.y, stopped.angular.z) == (0.0, 0.0, 0.0)
