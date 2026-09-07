# Copyright 2025-2026 Dimensional Inc.
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

import mujoco
import pytest

from dimos.hardware.manipulators.sim.adapter import ShmMujocoAdapter
from dimos.robot.alohamini2.arm_control import make_so101_trajectory, so101_hardware
from dimos.robot.alohamini2.config import ALOHA_MINI2_NAV_MJCF, ALOHA_MINI2_SO101_HOME
from dimos.robot.alohamini2.so101_home import (
    SO101_ARM_JOINTS,
    configure_articulated_so101,
    load_so101_home_pose,
    so101_home_joint_positions,
)
from dimos.simulation.engines.mujoco_engine import MujocoEngine
from dimos.simulation.engines.mujoco_shm import ManipShmWriter, shm_key_from_path
from dimos.simulation.engines.mujoco_sim_module import _WholeBodySimHooks
from dimos.utils.testing.waiting import wait_until


def test_hardware_views_address_disjoint_joint_slices() -> None:
    left = so101_hardware("left")
    right = so101_hardware("right")

    assert left.adapter_kwargs == {"joint_offset": 0, "gripper_index": 5}
    assert right.adapter_kwargs == {"joint_offset": 6, "gripper_index": 11}
    assert left.address == right.address
    assert left.joints == [f"left_arm/{name}" for name in SO101_ARM_JOINTS]
    assert right.joints == [f"right_arm/{name}" for name in SO101_ARM_JOINTS]


def test_joint_trajectory_starts_at_live_state_and_reaches_target() -> None:
    current = {f"left_arm/{name}": float(index) for index, name in enumerate(SO101_ARM_JOINTS)}
    target = {
        "shoulder_pan": 0.1,
        "shoulder_lift": -0.2,
        "elbow_flex": 0.3,
        "wrist_flex": -0.4,
        "wrist_roll": 0.5,
    }

    trajectory = make_so101_trajectory("left", current, target, duration=2.5)

    assert trajectory.joint_names == [f"left_arm/{name}" for name in SO101_ARM_JOINTS]
    assert trajectory.points[0].positions == list(current.values())
    assert trajectory.points[1].positions == list(target.values())
    assert trajectory.duration == 2.5


def test_joint_trajectory_rejects_out_of_range_target() -> None:
    current = {f"right_arm/{name}": 0.0 for name in SO101_ARM_JOINTS}
    target = {name: 0.0 for name in SO101_ARM_JOINTS}
    target["elbow_flex"] = 2.0

    with pytest.raises(ValueError, match="elbow_flex"):
        make_so101_trajectory("right", current, target, duration=1.0)


@pytest.mark.mujoco
def test_dual_adapters_command_one_articulated_mujoco_model() -> None:
    spec = mujoco.MjSpec.from_file(str(ALOHA_MINI2_NAV_MJCF))
    configure_articulated_so101(spec)
    model = spec.compile()
    model.opt.gravity[:] = 0.0
    home = so101_home_joint_positions(load_so101_home_pose(ALOHA_MINI2_SO101_HOME))
    engine = MujocoEngine(
        config_path=ALOHA_MINI2_NAV_MJCF,
        model=model,
        headless=True,
        reset_joint_positions=home,
    )
    writer = ManipShmWriter(shm_key_from_path(ALOHA_MINI2_NAV_MJCF))
    hooks = _WholeBodySimHooks(writer, dof=12)
    engine.set_step_hooks(before=hooks.pre_step, after=hooks.post_step)
    left = ShmMujocoAdapter(
        dof=5,
        address=str(ALOHA_MINI2_NAV_MJCF),
        joint_offset=0,
        gripper_index=5,
    )
    right = ShmMujocoAdapter(
        dof=5,
        address=str(ALOHA_MINI2_NAV_MJCF),
        joint_offset=6,
        gripper_index=11,
    )

    try:
        assert engine.connect() is True
        writer.signal_ready(num_joints=12)
        assert left.connect() is True
        assert right.connect() is True
        wait_until(
            lambda: left.read_joint_positions() == pytest.approx(home[:5], abs=1e-3),
            timeout=2.0,
            interval=0.01,
        )
        right_before = right.read_joint_positions()
        left_target = list(home[:5])
        left_target[0] = 0.25

        assert left.write_joint_positions(left_target) is True
        wait_until(
            lambda: left.read_joint_positions()[0] == pytest.approx(0.25, abs=2e-2),
            timeout=2.0,
            interval=0.01,
        )

        assert right.read_joint_positions() == pytest.approx(right_before, abs=2e-2)
    finally:
        left.disconnect()
        right.disconnect()
        engine.disconnect()
        writer.cleanup()
