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

"""Tests for ShmMujocoAdapter (the SHM-backed ManipulatorAdapter)."""

from __future__ import annotations

import uuid

import pytest

import dimos.hardware.manipulators.sim.adapter as adapter_mod
from dimos.hardware.manipulators.sim.adapter import ShmMujocoAdapter
from dimos.hardware.manipulators.spec import ControlMode, ManipulatorAdapter
from dimos.simulation.engines.mujoco_shm import ManipShmWriter

ARM_DOF = 7


@pytest.fixture
def shm_key():
    return f"test_{uuid.uuid4().hex[:10]}"


@pytest.fixture
def writer(shm_key, monkeypatch):
    """Pretend we're the sim module: create SHM, signal ready.

    We monkey-patch ``shm_key_from_path`` so the adapter under test resolves
    to our fixture's key regardless of the address string.
    """
    monkeypatch.setattr(adapter_mod, "shm_key_from_path", lambda _: shm_key)
    w = ManipShmWriter(shm_key)
    w.signal_ready(num_joints=ARM_DOF)
    yield w
    w.cleanup()


@pytest.fixture
def writer_with_gripper(shm_key, monkeypatch):
    monkeypatch.setattr(adapter_mod, "shm_key_from_path", lambda _: shm_key)
    w = ManipShmWriter(shm_key)
    w.signal_ready(num_joints=ARM_DOF + 1)
    yield w
    w.cleanup()


@pytest.fixture
def dual_arm_writer(shm_key, monkeypatch):
    monkeypatch.setattr(adapter_mod, "shm_key_from_path", lambda _: shm_key)
    w = ManipShmWriter(shm_key)
    w.initialize_position_command([float(i) for i in range(12)])
    w.write_joint_state(
        positions=[float(i) for i in range(12)],
        velocities=[float(i) / 10.0 for i in range(12)],
        efforts=[-float(i) for i in range(12)],
    )
    w.signal_ready(num_joints=12)
    yield w
    w.cleanup()


@pytest.fixture
def adapter(writer):
    a = ShmMujocoAdapter(dof=ARM_DOF, address="/fake/scene.xml")
    assert a.connect() is True
    yield a
    a.disconnect()


@pytest.fixture
def adapter_with_gripper(writer_with_gripper):
    a = ShmMujocoAdapter(dof=ARM_DOF, address="/fake/scene.xml")
    assert a.connect() is True
    yield a
    a.disconnect()


class TestProtocolConformance:
    def test_implements_manipulator_adapter(self):
        a = ShmMujocoAdapter(dof=ARM_DOF, address="/fake/scene.xml")
        assert isinstance(a, ManipulatorAdapter)

    def test_address_required(self):
        with pytest.raises(ValueError, match="address"):
            ShmMujocoAdapter(dof=ARM_DOF, address=None)

    def test_registered(self):
        from dimos.hardware.manipulators.registry import adapter_registry

        assert adapter_registry._factory_paths["sim_mujoco"] == (
            "dimos.hardware.manipulators.sim.adapter:ShmMujocoAdapter"
        )


class TestReadState:
    def test_read_joint_positions(self, adapter, writer):
        writer.write_joint_state(
            positions=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
            velocities=[0.0] * 7,
            efforts=[0.0] * 7,
        )
        assert adapter.read_joint_positions() == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]

    def test_read_joint_velocities(self, adapter, writer):
        writer.write_joint_state(
            positions=[0.0] * 7,
            velocities=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
            efforts=[0.0] * 7,
        )
        assert adapter.read_joint_velocities() == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]

    def test_read_joint_efforts(self, adapter, writer):
        writer.write_joint_state(
            positions=[0.0] * 7,
            velocities=[0.0] * 7,
            efforts=[-1.0, -2.0, -3.0, -4.0, -5.0, -6.0, -7.0],
        )
        assert adapter.read_joint_efforts() == [-1.0, -2.0, -3.0, -4.0, -5.0, -6.0, -7.0]

    def test_returns_only_dof_joints(self, adapter_with_gripper, writer_with_gripper):
        # Writer publishes 8 joints (7 arm + 1 gripper); adapter should return 7.
        writer_with_gripper.write_joint_state(
            positions=list(range(8)),
            velocities=[0.0] * 8,
            efforts=[0.0] * 8,
        )
        positions = adapter_with_gripper.read_joint_positions()
        assert len(positions) == ARM_DOF


class TestWriteCommand:
    def test_write_joint_positions(self, adapter, writer):
        assert adapter.write_joint_positions([0.1] * 7) is True
        cmd = writer.read_position_command(7)
        assert cmd is not None
        assert cmd.tolist() == pytest.approx([0.1] * 7)

    def test_write_joint_velocities(self, adapter, writer):
        assert adapter.write_joint_velocities([0.5] * 7) is True
        cmd = writer.read_velocity_command(7)
        assert cmd is not None
        assert cmd.tolist() == pytest.approx([0.5] * 7)

    def test_write_when_disabled(self, adapter):
        adapter.write_enable(False)
        assert adapter.write_joint_positions([0.0] * 7) is False

    def test_control_mode_tracked(self, adapter):
        adapter.write_joint_positions([0.0] * 7)
        assert adapter.get_control_mode() == ControlMode.POSITION
        adapter.write_joint_velocities([0.0] * 7)
        assert adapter.get_control_mode() == ControlMode.VELOCITY


class TestGripper:
    def test_gripper_detected(self, adapter_with_gripper):
        assert adapter_with_gripper._has_gripper is True

    def test_no_gripper_when_dof_matches(self, adapter):
        assert adapter._has_gripper is False

    def test_read_gripper_position(self, adapter_with_gripper, writer_with_gripper):
        writer_with_gripper.write_gripper_state(0.33)
        assert adapter_with_gripper.read_gripper_position() == pytest.approx(0.33)

    def test_read_gripper_position_no_gripper(self, adapter):
        assert adapter.read_gripper_position() is None

    def test_write_gripper_position(self, adapter_with_gripper, writer_with_gripper):
        assert adapter_with_gripper.write_gripper_position(0.5) is True
        # Gripper command is raw (unscaled) — sim module handles joint->ctrl.
        assert writer_with_gripper.read_gripper_command() == pytest.approx(0.5)

    def test_write_gripper_position_no_gripper(self, adapter):
        assert adapter.write_gripper_position(0.5) is False


class TestJointSlices:
    def test_two_adapters_read_independent_arm_and_gripper_slices(self, dual_arm_writer):
        left = ShmMujocoAdapter(
            dof=5,
            address="/fake/scene.xml",
            joint_offset=0,
            gripper_index=5,
        )
        right = ShmMujocoAdapter(
            dof=5,
            address="/fake/scene.xml",
            joint_offset=6,
            gripper_index=11,
        )
        try:
            assert left.connect() is True
            assert right.connect() is True

            assert left.read_joint_positions() == [0.0, 1.0, 2.0, 3.0, 4.0]
            assert right.read_joint_positions() == [6.0, 7.0, 8.0, 9.0, 10.0]
            assert left.read_gripper_position() == 5.0
            assert right.read_gripper_position() == 11.0
        finally:
            left.disconnect()
            right.disconnect()

    def test_slice_commands_preserve_the_other_arm_targets(self, dual_arm_writer):
        left = ShmMujocoAdapter(
            dof=5,
            address="/fake/scene.xml",
            joint_offset=0,
            gripper_index=5,
        )
        right = ShmMujocoAdapter(
            dof=5,
            address="/fake/scene.xml",
            joint_offset=6,
            gripper_index=11,
        )
        try:
            assert left.connect() is True
            assert right.connect() is True
            assert left.write_joint_positions([0.1] * 5) is True
            first = dual_arm_writer.read_position_command(12)
            assert first is not None
            assert first.tolist() == pytest.approx([0.1] * 5 + list(range(5, 12)))

            assert right.write_joint_positions([-0.2] * 5) is True
            assert right.write_gripper_position(0.7) is True
            second = dual_arm_writer.read_position_command(12)
            assert second is not None
            assert second.tolist() == pytest.approx([0.1] * 5 + [5.0] + [-0.2] * 5 + [0.7])
        finally:
            left.disconnect()
            right.disconnect()


class TestConnect:
    def test_connect_before_sim_ready_times_out(self, shm_key, monkeypatch):
        """If sim module never signals ready, connect() returns False after timeout."""
        monkeypatch.setattr(adapter_mod, "shm_key_from_path", lambda _: shm_key)
        # Shrink timeouts so the test runs fast.
        monkeypatch.setattr(adapter_mod, "_READY_WAIT_TIMEOUT_S", 0.2)
        monkeypatch.setattr(adapter_mod, "_READY_WAIT_POLL_S", 0.02)

        w = ManipShmWriter(shm_key)
        try:
            # Note: writer exists but signal_ready is NOT called.
            a = ShmMujocoAdapter(dof=ARM_DOF, address="/fake/scene.xml")
            assert a.connect() is False
        finally:
            w.cleanup()

    def test_connect_waits_for_shm(self, shm_key, monkeypatch):
        """If SHM buffers don't exist yet, connect() retries briefly."""
        monkeypatch.setattr(adapter_mod, "shm_key_from_path", lambda _: shm_key)
        monkeypatch.setattr(adapter_mod, "_ATTACH_RETRY_TIMEOUT_S", 0.2)
        monkeypatch.setattr(adapter_mod, "_ATTACH_RETRY_POLL_S", 0.02)

        a = ShmMujocoAdapter(dof=ARM_DOF, address="/fake/scene.xml")
        # SHM was never created — attach must time out.
        assert a.connect() is False
