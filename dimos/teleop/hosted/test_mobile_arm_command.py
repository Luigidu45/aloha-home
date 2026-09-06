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

"""Base drive and torso jog on the hosted mobile arm command plane."""

from __future__ import annotations

from collections.abc import Iterator
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from dimos.core.module import Module
from dimos.msgs.sensor_msgs.Joy import Joy
from dimos.teleop.hosted.mobile_arm_command import MobileArmCommandModule

_PORTS = (
    "left_controller_output",
    "right_controller_output",
    "teleop_buttons",
    "left_gripper_command",
    "right_gripper_command",
    "cmd_ack",
    "robot_state",
    "ee_twist_command",
    "gripper_command",
    "twist_command",
    "head_cartesian_command",
    "coordinator",
)


@pytest.fixture
def module(monkeypatch: pytest.MonkeyPatch) -> Iterator[MobileArmCommandModule]:
    def _fake_init(self: Any, **kwargs: Any) -> None:
        self.config = SimpleNamespace(
            control_loop_hz=50.0,
            cmd_stale_after_sec=0.5,
            enable_ui_scaling=False,
            input_timeout_s=1.0,
            base_linear_speed=0.3,
            base_angular_speed=0.4,
            base_deadzone=0.15,
            torso_deadzone=0.25,
            torso_speed=0.15,
            torso_travel=0.25,
        )

    monkeypatch.setattr(Module, "__init__", _fake_init)
    module = MobileArmCommandModule()
    for port in _PORTS:
        setattr(module, port, MagicMock())
    module._cmd.start()
    yield module
    module._cmd.stop()


def _joy(frame_id: str, x: float = 0.0, y: float = 0.0, primary: bool = False) -> bytes:
    return Joy(
        frame_id=frame_id,
        axes=[x, y, 0.0, 0.0],
        buttons=[0, 0, 0, 0, int(primary), 0, 0],
    ).lcm_encode()


def _last_twist(module: MobileArmCommandModule) -> Any:
    return module.twist_command.publish.call_args[0][0]


def _last_head_z(module: MobileArmCommandModule) -> float:
    return float(module.head_cartesian_command.publish.call_args[0][0].position.z)


def test_thumbsticks_drive_the_base(module: MobileArmCommandModule) -> None:
    """Right stick translates, left stick X yaws, both past the deadzone."""
    module._on_joy_bytes(_joy("right", x=0.5, y=-1.0))
    module._on_joy_bytes(_joy("left", x=-1.0))

    twist = _last_twist(module)
    assert twist.linear.x == pytest.approx(0.3)  # stick forward is negative y
    assert twist.linear.y == pytest.approx(-0.15)
    assert twist.angular.z == pytest.approx(0.4)


def test_stick_drift_inside_the_deadzone_does_not_move_the_base(
    module: MobileArmCommandModule,
) -> None:
    module._on_joy_bytes(_joy("right", x=0.1, y=0.1))
    module._on_joy_bytes(_joy("left", x=0.1))

    twist = _last_twist(module)
    assert (twist.linear.x, twist.linear.y, twist.angular.z) == (0.0, 0.0, 0.0)


def test_left_stick_y_jogs_the_torso_and_clamps_at_travel(
    module: MobileArmCommandModule,
) -> None:
    """The head target is published every message, and rides up to torso_travel."""
    module._on_joy_bytes(_joy("left", y=0.0))
    assert _last_head_z(module) == pytest.approx(0.0)

    # Enough held-stick time to run past the 0.25 m clamp at 0.15 m/s.
    for _ in range(60):
        module._last_jog_t = time.monotonic() - 0.1
        module._on_joy_bytes(_joy("left", y=-1.0))

    assert _last_head_z(module) == pytest.approx(0.25)


def test_releasing_the_deadman_rebaselines_the_torso_offset(
    module: MobileArmCommandModule,
) -> None:
    """The task recaptures its head reference on re-engage, so the offset must
    restart at zero or the operator loses travel every session."""
    module._on_joy_bytes(_joy("right", primary=True))
    module._last_jog_t = time.monotonic() - 0.5
    module._on_joy_bytes(_joy("left", y=-1.0, primary=True))
    assert _last_head_z(module) > 0.0

    module._on_joy_bytes(_joy("left", y=0.0, primary=False))
    assert _last_head_z(module) == pytest.approx(0.0)


def test_estop_stops_the_base_and_freezes_the_torso(module: MobileArmCommandModule) -> None:
    module._last_jog_t = time.monotonic() - 0.5
    module._on_joy_bytes(_joy("left", y=-1.0))
    held = _last_head_z(module)
    assert held > 0.0

    module._handle_estop(nonce="n1")
    module._last_jog_t = time.monotonic() - 0.5
    module._on_joy_bytes(_joy("right", x=1.0, y=-1.0))
    module._on_joy_bytes(_joy("left", y=-1.0))

    twist = _last_twist(module)
    assert (twist.linear.x, twist.linear.y, twist.angular.z) == (0.0, 0.0, 0.0)
    assert _last_head_z(module) == pytest.approx(held)
