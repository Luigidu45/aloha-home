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

import math
from pathlib import Path

import mujoco
import pytest

from dimos.robot.alohamini2.config import ALOHA_MINI2_NAV_MJCF
from dimos.robot.alohamini2.so101_home import (
    SO101_ALL_JOINTS,
    SO101_JOINT_RANGES,
    SO101_SIDES,
    apply_so101_home_pose,
    configure_articulated_so101,
    default_so101_home_pose,
    load_so101_home_pose,
    save_so101_home_pose,
    so101_home_joint_positions,
)
from dimos.robot.alohamini2.tools.calibrate_so101_home import build_calibration_model


def test_saved_pose_round_trips_and_does_not_share_default_state(tmp_path: Path) -> None:
    path = tmp_path / "home.json"
    pose = default_so101_home_pose()
    pose["left"]["shoulder_pan"] = 0.25

    save_so101_home_pose(path, pose)

    assert load_so101_home_pose(path) == pose
    assert default_so101_home_pose()["left"]["shoulder_pan"] == 0.0


def test_pose_rejects_joint_values_outside_physical_limits(tmp_path: Path) -> None:
    pose = default_so101_home_pose()
    pose["right"]["elbow_flex"] = SO101_JOINT_RANGES["elbow_flex"][1] + 0.01

    with pytest.raises(ValueError, match="right elbow_flex"):
        save_so101_home_pose(tmp_path / "home.json", pose)


def test_degree_conversion_roundoff_at_joint_limit_is_clamped(tmp_path: Path) -> None:
    path = tmp_path / "home.json"
    pose = default_so101_home_pose()
    pose["left"]["shoulder_lift"] = math.radians(-100.0)

    save_so101_home_pose(path, pose)

    saved = load_so101_home_pose(path)
    assert saved["left"]["shoulder_lift"] == SO101_JOINT_RANGES["shoulder_lift"][0]


@pytest.mark.mujoco
def test_saved_angles_are_baked_into_both_rigid_arm_trees() -> None:
    spec = mujoco.MjSpec.from_file(str(ALOHA_MINI2_NAV_MJCF))
    pose = default_so101_home_pose()
    pose["left"]["shoulder_pan"] = 0.4
    pose["right"]["shoulder_pan"] = -0.3

    apply_so101_home_pose(spec, pose)
    model = spec.compile()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    left_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cad_left_so101_shoulder_body")
    right_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cad_right_so101_shoulder_body")

    assert tuple(data.xquat[left_id]) != pytest.approx(tuple(data.xquat[right_id]))
    assert model.nq == 7
    assert model.nu == 0


@pytest.mark.mujoco
def test_calibration_model_exposes_every_joint_for_each_arm() -> None:
    model = build_calibration_model()

    for side in SO101_SIDES:
        for joint_name, limits in SO101_JOINT_RANGES.items():
            joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, f"{side}_{joint_name}")
            assert joint_id >= 0
            assert tuple(model.jnt_range[joint_id]) == pytest.approx(limits)
    assert model.nq == 19


@pytest.mark.mujoco
def test_articulated_model_exposes_ordered_dual_arm_actuators() -> None:
    spec = mujoco.MjSpec.from_file(str(ALOHA_MINI2_NAV_MJCF))

    configure_articulated_so101(spec)
    model = spec.compile()

    expected_names = [
        f"{side}_{joint_name}_position" for side in SO101_SIDES for joint_name in SO101_ALL_JOINTS
    ]
    actual_names = [
        mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, index) for index in range(model.nu)
    ]
    assert actual_names == expected_names
    assert model.nu == 12


def test_home_positions_follow_dual_arm_actuator_order() -> None:
    pose = default_so101_home_pose()
    pose["left"]["shoulder_pan"] = 0.2
    pose["right"]["shoulder_pan"] = -0.3

    positions = so101_home_joint_positions(pose)

    assert positions[:6] == [pose["left"][name] for name in SO101_ALL_JOINTS]
    assert positions[6:] == [pose["right"][name] for name in SO101_ALL_JOINTS]
