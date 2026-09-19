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

"""Check the supplied CAD geometry without assigning invented joint limits."""

import json
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from dimos.robot.alohamini1.config import (
    ALOHA_MINI1_NAV_CAMERAS,
    ALOHA_MINI1_NAV_HEIGHT_M,
    ALOHA_MINI1_NAV_MJCF,
    ALOHA_MINI1_NAV_ROTATION_DIAMETER_M,
    ALOHA_MINI1_NAV_WIDTH_M,
    ALOHA_MINI1_RGB_CAMERAS,
)


@pytest.fixture
def model():
    return mujoco.MjModel.from_xml_path(str(ALOHA_MINI1_NAV_MJCF))


def test_all_urdf_link_frames_and_inertial_mass_are_preserved(model):
    urdf = ET.parse(ALOHA_MINI1_NAV_MJCF.parent / "source.urdf").getroot()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    expected = {"base_link": np.eye(4)}
    expected["base_link"][:3, :3] = Rotation.from_euler("z", np.pi / 2).as_matrix()
    expected["base_link"][2, 3] = 0.005
    joints = urdf.findall("joint")
    while joints:
        ready = [j for j in joints if j.find("parent").get("link") in expected]
        assert ready
        for joint in ready:
            origin = joint.find("origin")
            transform = np.eye(4)
            transform[:3, 3] = np.fromstring(origin.get("xyz"), sep=" ")
            transform[:3, :3] = Rotation.from_euler(
                "xyz", np.fromstring(origin.get("rpy"), sep=" ")
            ).as_matrix()
            child = joint.find("child").get("link")
            expected[child] = expected[joint.find("parent").get("link")] @ transform
            np.testing.assert_allclose(data.body(child).xpos, expected[child][:3, 3], atol=1e-9)
            np.testing.assert_allclose(
                data.body(child).xmat.reshape(3, 3), expected[child][:3, :3], atol=1e-9
            )
            joints.remove(joint)
    mass = sum(float(link.find("inertial/mass").get("value")) for link in urdf.findall("link"))
    assert model.body_mass.sum() == pytest.approx(mass)


def test_missing_limits_never_become_actuated_arms(model):
    manifest = json.loads((ALOHA_MINI1_NAV_MJCF.parent / "manifest.json").read_text())
    assert model.nu == 0
    assert model.njnt == 1
    assert model.joint("root").type == mujoco.mjtJoint.mjJNT_FREE
    locked = manifest["locked_joints"]
    assert sum(j["reason"] == "zero_urdf_limits" for j in locked) == 13
    assert sum(j["reason"] == "navigation_wheel_proxy" for j in locked) == 3
    assert manifest["physical_validated"] is False
    assert model.nmesh in (19, 23)
    assert {model.cam(i).name for i in range(model.ncam)} == set(
        ALOHA_MINI1_RGB_CAMERAS + ALOHA_MINI1_NAV_CAMERAS
    )
    assert model.cam("left_camera").bodyid == model.body("left_link5").id
    assert model.cam("right_camera").bodyid == model.body("right_link5").id


def test_navigation_envelope_contains_cad_zero_meshes(model):
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    points = []
    for i in range(model.ngeom):
        if model.geom_group[i] != 2:
            continue
        mesh = model.geom_dataid[i]
        start = model.mesh_vertadr[mesh]
        count = model.mesh_vertnum[mesh]
        points.append(
            model.mesh_vert[start : start + count] @ data.geom_xmat[i].reshape(3, 3).T
            + data.geom_xpos[i]
            - data.body("base_link").xpos
        )
    points = np.vstack(points)
    assert np.max(np.abs(points[:, 1])) * 2 < ALOHA_MINI1_NAV_WIDTH_M
    assert np.max(np.linalg.norm(points[:, :2], axis=1)) * 2 < ALOHA_MINI1_NAV_ROTATION_DIAMETER_M
    assert np.max(points[:, 2]) < ALOHA_MINI1_NAV_HEIGHT_M
