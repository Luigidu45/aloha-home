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

"""R1 Pro hosted teleoperation over the dimensional-teleop broker.

One operator session covers both arms (controller poses through the shared
teleoperation IK task), the holonomic chassis (right stick), and the torso
height (left stick Y).

``r1pro-hosted-teleop-quest`` and ``r1pro-hosted-teleop-pico`` are the same
stack: both headsets deliver WebXR poses and Joy over the same datachannel, so
nothing robot-side distinguishes them. They exist as separate names so the
demo has one entry point per headset and a place to pin a device-specific
deadzone or stick mapping once each is measured on hardware.

Name the robot in the operator console with ``TRANSPORTS__BROKER__ROBOT_NAME``
rather than in the blueprint: broker settings are part of the provider's
singleton key, so differing them per stream would open a second session.

Usage:
    TRANSPORTS__BROKER__API_KEY=dtk_live_... \\
    TRANSPORTS__BROKER__ROBOT_NAME=r1pro \\
    dimos run r1pro-hosted-teleop-quest
"""

from __future__ import annotations

from dimos.control.components import make_twist_base_joints
from dimos.control.coordinator import TaskConfig
from dimos.control.tasks.trajectory_task.trajectory_task import joint_trajectory_task
from dimos.control.teleop_coordinator import TeleopControlCoordinator
from dimos.core.coordination.blueprints import Blueprint, autoconnect
from dimos.core.transport import CloudflareTransport, CloudflareVideoTransport
from dimos.msgs.sensor_msgs.Image import Image
from dimos.robot.galaxea.r1pro.blueprints.basic.r1pro_coordinator import (
    r1pro_control,
    r1pro_whole_body_hardware,
)
from dimos.robot.galaxea.r1pro.config import (
    R1PRO_UPPER_BODY_PLANNING_JOINTS,
    make_r1pro_model_config,
)
from dimos.robot.galaxea.r1pro.teleop_ik import R1ProPinkPoseTargetSolver
from dimos.robot.manipulators.common.blueprints import teleop_ik_task
from dimos.teleop.hosted.camera_mux import CameraMuxModule
from dimos.teleop.hosted.hosted_stats import HostedStatsModule
from dimos.teleop.hosted.image_decode import ImageDecodeModule
from dimos.teleop.hosted.mobile_arm_command import MobileArmCommandModule
from dimos.teleop.hosted.robot_type import RobotType

R1PRO_HOSTED_TASK_NAME = "teleop_r1pro"


# Distinct classes only because blueprints can't yet run two instances of one
# module (same reason the hosted xArm blueprints declare Front/WristCamera).
class HeadCameraDecode(ImageDecodeModule):
    pass


class WristCameraDecode(ImageDecodeModule):
    pass


def _teleop_tasks() -> list[TaskConfig]:
    """Bimanual IK with a head target for the torso, plus chassis velocity.

    The head target is not the operator's headset here: MobileArmCommandModule
    publishes a stick-jogged height on that stream, so the solver's
    forward/vertical head constraint becomes the torso jog.
    """
    return [
        teleop_ik_task(
            r1pro_whole_body_hardware(),
            name=R1PRO_HOSTED_TASK_NAME,
            robot_model=make_r1pro_model_config(),
            joint_names=R1PRO_UPPER_BODY_PLANNING_JOINTS,
            bindings=[
                {"hand": "left", "target_frame": "left_gripper_link"},
                {"hand": "right", "target_frame": "right_gripper_link"},
            ],
            head_target_frame=R1ProPinkPoseTargetSolver.HEAD_FRAME,
            solver_type=R1ProPinkPoseTargetSolver,
        ),
        TaskConfig(
            name="vel_chassis",
            type="velocity",
            joint_names=make_twist_base_joints("chassis"),
            priority=10,
        ),
        # Preempts teleoperation through normal arbitration, so a planned move
        # clears the engagement instead of fighting it.
        joint_trajectory_task(list(R1PRO_UPPER_BODY_PLANNING_JOINTS), priority=20),
    ]


def r1pro_hosted_teleop() -> Blueprint:
    """Broker-facing modules plus the real R1 Pro control stack.

    Head-left and right-wrist colour are decoded to raw frames for the mux;
    the R1 Pro driver only publishes them compressed.
    """
    return (
        autoconnect(
            MobileArmCommandModule.blueprint(),
            HostedStatsModule.blueprint(),
            CameraMuxModule.blueprint(cameras=["cam1", "cam2"]),
            HeadCameraDecode.blueprint(),
            WristCameraDecode.blueprint(),
            r1pro_control(
                tasks=_teleop_tasks(),
                coordinator_cls=TeleopControlCoordinator,
            ),
        )
        .remappings(
            [
                (HeadCameraDecode, "compressed_in", "head_left_color"),
                (HeadCameraDecode, "image_out", "cam1"),
                (WristCameraDecode, "compressed_in", "wrist_right_color"),
                (WristCameraDecode, "image_out", "cam2"),
                (MobileArmCommandModule, "left_controller_output", "left_cartesian_command"),
                (MobileArmCommandModule, "right_controller_output", "right_cartesian_command"),
            ]
        )
        .transports(
            {
                # Inbound operator planes. cmd_raw carries the WebXR controller
                # poses and Joy; state_json carries gripper / E-STOP / scale.
                ("cmd_raw", bytes): CloudflareTransport.spec("cmd_unreliable"),
                ("state_json", bytes): CloudflareTransport.spec(
                    "state_reliable", robot_type=RobotType.ARM
                ),
                ("camera_select", bytes): CloudflareTransport.spec("state_reliable"),
                # Outbound operator planes.
                ("mux_image", Image): CloudflareVideoTransport.spec(),
                ("telemetry_out", bytes): CloudflareTransport.spec("state_reliable_back"),
                ("cmd_ack", bytes): CloudflareTransport.spec("state_reliable_back"),
            }
        )
        # The R1 Pro sensor bus is Zenoh; only the operator planes above ride
        # Cloudflare. autoconnect merges global config last-wins, so pin both.
        .global_config(transport="zenoh", viewer="none", n_workers=4)
    )


# Wrapped in autoconnect so the blueprint-registry AST scan sees them; a bare
# helper call at module scope registers nothing.
r1pro_hosted_teleop_quest = autoconnect(r1pro_hosted_teleop())
r1pro_hosted_teleop_pico = autoconnect(r1pro_hosted_teleop())
