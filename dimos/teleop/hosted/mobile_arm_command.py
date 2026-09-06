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

"""Hosted command plane for a mobile bimanual robot.

Adds thumbstick base driving and a thumbstick-jogged torso height to
``ArmCommandModule``, so one operator session covers arms, chassis, and torso.
"""

from __future__ import annotations

import time
from typing import Any

from dimos.core.stream import Out
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Twist import Twist
from dimos.msgs.geometry_msgs.Vector3 import Vector3
from dimos.teleop.hosted.arm_command import ArmCommandConfig, ArmCommandModule
from dimos.teleop.quest.quest_types import Hand, QuestControllerState

# A Joy gap longer than this is a link stall, not a slow frame; clamping keeps
# one late message from stepping the torso through a large jump.
_MAX_JOG_STEP_S = 0.2


class MobileArmCommandConfig(ArmCommandConfig):
    base_linear_speed: float = 0.3
    base_angular_speed: float = 0.4
    base_deadzone: float = 0.15
    torso_deadzone: float = 0.25
    torso_speed: float = 0.15
    # Vertical range either side of the height captured when the hands engage.
    torso_travel: float = 0.25


class MobileArmCommandModule(ArmCommandModule):
    """Arm command plane plus holonomic base drive and torso height.

    Right stick translates the base, left stick X yaws it, left stick Y jogs a
    vertical offset published as the teleoperation task's head target. Base
    driving is always live; the torso only moves while the task is engaged,
    because the task captures its head reference on engagement.
    """

    config: MobileArmCommandConfig

    twist_command: Out[Twist]
    head_cartesian_command: Out[PoseStamped]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._torso_z = 0.0
        self._last_jog_t: float | None = None
        self._deadman_held = False

    def _publish_safe_command(self) -> None:
        self.twist_command.publish(Twist.zero())

    @staticmethod
    def _deadzone(value: float, threshold: float) -> float:
        return 0.0 if abs(value) < threshold else value

    def _on_joy_bytes(self, data: bytes) -> bool:
        try:
            valid = super()._on_joy_bytes(data)
        except ValueError:
            self._publish_safe_command()
            raise
        if not valid:
            self._publish_safe_command()
            return False
        with self._lock:
            left = self._controllers.get(Hand.LEFT)
            right = self._controllers.get(Hand.RIGHT)
        self._track_deadman(left, right)
        self._publish_base_twist(left, right)
        self._publish_torso_target(left)
        return True

    def _track_deadman(
        self,
        left: QuestControllerState | None,
        right: QuestControllerState | None,
    ) -> None:
        """Rebaseline the torso offset when the task's deadman is released.

        The task recaptures its head reference on the next engagement, so the
        offset must restart at zero or the operator loses travel each session.
        """
        held = (
            left is not None and left.primary and right is not None and right.primary
        ) and not self._estopped
        if self._deadman_held and not held:
            self._torso_z = 0.0
        self._deadman_held = held

    def _publish_base_twist(
        self,
        left: QuestControllerState | None,
        right: QuestControllerState | None,
    ) -> None:
        if self._estopped:
            self._publish_safe_command()
            return
        twist = Twist()
        twist.linear = Vector3(0.0, 0.0, 0.0)
        twist.angular = Vector3(0.0, 0.0, 0.0)
        deadzone = self.config.base_deadzone
        if right is not None:
            twist.linear.x = (
                -self._deadzone(right.thumbstick.y, deadzone) * self.config.base_linear_speed
            )
            twist.linear.y = (
                -self._deadzone(right.thumbstick.x, deadzone) * self.config.base_linear_speed
            )
        if left is not None:
            twist.angular.z = (
                -self._deadzone(left.thumbstick.x, deadzone) * self.config.base_angular_speed
            )
        self.twist_command.publish(twist)

    def _publish_torso_target(self, left: QuestControllerState | None) -> None:
        """Integrate the left stick into a height and publish it as the head target.

        Published every Joy message even at rest: the task needs a live head
        pose to capture its reference and to stay active.
        """
        now = time.monotonic()
        elapsed = 0.0 if self._last_jog_t is None else min(now - self._last_jog_t, _MAX_JOG_STEP_S)
        self._last_jog_t = now

        axis = 0.0
        if left is not None and not self._estopped:
            axis = -self._deadzone(left.thumbstick.y, self.config.torso_deadzone)
        travel = self.config.torso_travel
        self._torso_z = min(
            travel, max(-travel, self._torso_z + axis * self.config.torso_speed * elapsed)
        )
        self.head_cartesian_command.publish(
            PoseStamped(position=[0.0, 0.0, self._torso_z], ts=time.time(), frame_id="head")
        )

    def _handle_estop(self, nonce: Any) -> None:
        super()._handle_estop(nonce)
        self._publish_safe_command()

    def _on_operator_lost(self) -> None:
        super()._on_operator_lost()
        self._publish_safe_command()
