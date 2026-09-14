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

"""Original robot kinematics, independent actuators and collision regressions."""

import json
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from dimos.robot.alohamini2.config import ALOHA_MINI2_AM_ARM200_MJCF
from dimos.robot.alohamini2.sim_module import (
    AlohaMini2SimModule,
    PlanarVelocity,
    apply_planar_velocity,
)
from dimos.simulation.engines.mujoco_engine import MujocoEngine


@pytest.fixture
def model():
    return mujoco.MjModel.from_xml_path(str(ALOHA_MINI2_AM_ARM200_MJCF))


@pytest.mark.parametrize("angle", [0.0, 0.12, -0.1])
def test_original_urdf_fk_matches_both_arms_and_elevator(model, angle):
    data = mujoco.MjData(model)
    urdf = ET.parse(ALOHA_MINI2_AM_ARM200_MJCF.parent / "source.urdf").getroot()
    expected = {"base_link": np.eye(4)}
    expected["base_link"][:3, :3] = Rotation.from_euler("z", np.pi / 2).as_matrix()
    expected["base_link"][2, 3] = 0.005
    joints = [j for j in urdf.findall("joint") if not j.attrib["name"].startswith("root_")]
    for joint in joints:
        if joint.attrib["type"] != "fixed":
            data.joint(joint.attrib["name"]).qpos[0] = (
                angle if joint.attrib["type"] == "revolute" else angle / 3
            )
    mujoco.mj_forward(model, data)
    while joints:
        ready = [j for j in joints if j.find("parent").attrib["link"] in expected]
        assert ready, "URDF graph must be connected"
        for joint in ready:
            transform = np.eye(4)
            origin = joint.find("origin")
            if origin is not None:
                transform[:3, 3] = np.fromstring(origin.get("xyz", "0 0 0"), sep=" ")
                transform[:3, :3] = Rotation.from_euler(
                    "xyz", np.fromstring(origin.get("rpy", "0 0 0"), sep=" ")
                ).as_matrix()
            motion = np.eye(4)
            kind = joint.attrib["type"]
            if kind != "fixed":
                axis = np.fromstring(joint.find("axis").attrib["xyz"], sep=" ")
                if kind == "revolute":
                    motion[:3, :3] = Rotation.from_rotvec(axis * angle).as_matrix()
                else:
                    motion[:3, 3] = axis * angle / 3
            child = joint.find("child").attrib["link"]
            expected[child] = expected[joint.find("parent").attrib["link"]] @ transform @ motion
            np.testing.assert_allclose(data.body(child).xpos, expected[child][:3, 3], atol=1e-9)
            np.testing.assert_allclose(
                data.body(child).xmat.reshape(3, 3), expected[child][:3, :3], atol=1e-9
            )
            joints.remove(joint)


def test_original_model_has_independent_six_axis_arms_and_no_zero_pose_self_penetration(model):
    manifest = json.loads((ALOHA_MINI2_AM_ARM200_MJCF.parent / "manifest.json").read_text())
    names = [model.joint(model.actuator_trnid[i, 0]).name for i in range(model.nu)]
    assert names == manifest["joint_order"]
    assert len(names) == 15
    assert names[0] == "vertical_move"
    assert names[5] == "left_wrist_yaw_joint"
    assert names[12] == "right_wrist_yaw_joint"
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    assert data.ncon == 0
    assert np.all(model.actuator_forcerange[:, 1] > 0)
    assert model.cam("left_camera").bodyid != model.cam("right_camera").bodyid


def test_pd_actuators_move_both_wrists_grippers_and_elevator(model):
    engine = MujocoEngine(config_path=ALOHA_MINI2_AM_ARM200_MJCF, model=model, headless=True)
    try:
        data = engine.data
        targets = {
            "left_wrist_roll": 0.15,
            "right_wrist_roll": -0.15,
            "left_gripper": 0.15,
            "right_gripper": 0.15,
            "vertical_move": 0.05,
        }
        for name, value in targets.items():
            data.ctrl[model.actuator(name + "_position").id] = value
        for _ in range(400):
            apply_planar_velocity(engine, PlanarVelocity(), base_height=0.005)
            mujoco.mj_step(model, data)
        for name, value in targets.items():
            assert data.joint(name).qpos[0] == pytest.approx(value, abs=0.025)
        assert np.isfinite(data.qpos).all()
        assert np.max(np.abs(data.qvel)) < 0.1
    finally:
        engine.disconnect()


def test_am_model_rejects_so101_configuration():
    module = AlohaMini2SimModule(arm_model="am_arm200", dof=12)
    try:
        with pytest.raises(ValueError, match="15 actuators"):
            module._configure_robot_spec(mujoco.MjSpec.from_file(str(ALOHA_MINI2_AM_ARM200_MJCF)))
    finally:
        module.stop()


@pytest.fixture
def sim_control(model, mocker):
    engine = MujocoEngine(config_path=ALOHA_MINI2_AM_ARM200_MJCF, model=model, headless=True)
    module = AlohaMini2SimModule(arm_model="am_arm200", dof=15)
    mocker.patch.object(module, "_engine", engine)
    try:
        yield module
    finally:
        module.stop()


@pytest.mark.parametrize("invalid", ["missing", "nan", "limit"])
def test_rpc_rejects_incomplete_or_invalid_joint_commands(sim_control, invalid, mocker):
    positions = sim_control.get_sim_joint_state()
    name = next(iter(positions))
    if invalid == "missing":
        positions.pop(name)
    else:
        positions[name] = float("nan") if invalid == "nan" else 10.0
    write = mocker.spy(sim_control._engine, "write_joint_command")
    with pytest.raises(ValueError):
        sim_control.set_sim_joint_positions(positions)
    write.assert_not_called()
