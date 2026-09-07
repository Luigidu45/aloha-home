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

"""Persistent SO101 home poses and their rigid/articulated MuJoCo representation."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any

import mujoco

SO101_SIDES = ("left", "right")
SO101_ARM_JOINTS = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
)
SO101_ALL_JOINTS = (*SO101_ARM_JOINTS, "gripper")
SO101_DOF_PER_ARM = len(SO101_ARM_JOINTS)
SO101_JOINTS_PER_SIDE = len(SO101_ALL_JOINTS)
SO101_TOTAL_SIM_JOINTS = len(SO101_SIDES) * SO101_JOINTS_PER_SIDE
SO101_LIMIT_TOLERANCE_RAD = 1e-9
SO101_JOINT_RANGES: dict[str, tuple[float, float]] = {
    "shoulder_pan": (-1.9198621771937616, 1.9198621771937634),
    "shoulder_lift": (-1.7453292519943224, 1.7453292519943366),
    "elbow_flex": (-1.69, 1.69),
    "wrist_flex": (-1.6580628494556928, 1.6580627293335335),
    "wrist_roll": (-2.7438472969992493, 2.841206309382605),
    "gripper": (-0.17453297762778586, 1.7453291995659765),
}

# Body-local transforms at zero joint position, copied from so101_new_calib.xml.
SO101_JOINT_BODIES: dict[str, tuple[str, tuple[float, float, float, float]]] = {
    "shoulder_pan": (
        "shoulder",
        (3.56167e-16, 1.22818e-15, -1.0, -4.14635e-16),
    ),
    "shoulder_lift": ("upper_arm", (0.5, -0.5, -0.5, -0.5)),
    "elbow_flex": ("lower_arm", (0.707106781, 0.0, 0.0, 0.707106781)),
    "wrist_flex": ("wrist", (0.707106781, 0.0, 0.0, -0.707106781)),
    "wrist_roll": (
        "gripper",
        (0.0172091082, -0.0172091082, 0.706897338, 0.706897338),
    ),
    "gripper": (
        "moving_jaw",
        (0.707106781, 0.707106781, -1.85362e-08, 1.85362e-08),
    ),
}

DEFAULT_SO101_HOME_POSE: dict[str, dict[str, float]] = {
    side: {
        "shoulder_pan": 0.0,
        "shoulder_lift": -1.7453292519943224,
        "elbow_flex": 1.5690509975429023,
        "wrist_flex": 1.0506882097005865,
        "wrist_roll": 0.0,
        "gripper": -0.17453292519943295,
    }
    for side in SO101_SIDES
}


def default_so101_home_pose() -> dict[str, dict[str, float]]:
    """Return an independent copy of the built-in home pose."""
    return deepcopy(DEFAULT_SO101_HOME_POSE)


def validate_so101_home_pose(value: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """Validate and normalize a complete dual-arm SO101 pose."""
    if set(value) != set(SO101_SIDES):
        raise ValueError("SO101 home pose must contain exactly 'left' and 'right'")

    normalized: dict[str, dict[str, float]] = {}
    for side in SO101_SIDES:
        raw_joints = value[side]
        if not isinstance(raw_joints, Mapping) or set(raw_joints) != set(SO101_JOINT_RANGES):
            raise ValueError(f"SO101 {side} pose must contain all six joints")
        normalized[side] = {}
        for joint_name, limits in SO101_JOINT_RANGES.items():
            angle = float(raw_joints[joint_name])
            if (
                not math.isfinite(angle)
                or angle < limits[0] - SO101_LIMIT_TOLERANCE_RAD
                or angle > limits[1] + SO101_LIMIT_TOLERANCE_RAD
            ):
                raise ValueError(f"SO101 {side} {joint_name}={angle} is outside {limits} radians")
            # Tk converts degrees back to radians. At an endpoint that can differ
            # from the URDF limit by a few ULPs, so clamp accepted round-off.
            normalized[side][joint_name] = min(max(angle, limits[0]), limits[1])
    return normalized


def load_so101_home_pose(path: Path) -> dict[str, dict[str, float]]:
    """Load a saved pose, falling back to the built-in pose when absent."""
    if not path.exists():
        return default_so101_home_pose()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError(f"Unsupported SO101 home pose file: {path}")
    pose = payload.get("pose")
    if not isinstance(pose, dict):
        raise ValueError(f"Missing SO101 pose in {path}")
    return validate_so101_home_pose(pose)


def save_so101_home_pose(path: Path, pose: Mapping[str, Any]) -> None:
    """Atomically persist a validated dual-arm pose."""
    normalized = validate_so101_home_pose(pose)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps({"version": 1, "pose": normalized}, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _multiply_wxyz(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    aw, ax, ay, az = first
    bw, bx, by, bz = second
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def joint_body_quaternion(
    base_quaternion: tuple[float, float, float, float], angle: float
) -> tuple[float, float, float, float]:
    """Bake a local Z-axis hinge angle into a MuJoCo body quaternion."""
    half_angle = angle * 0.5
    result = _multiply_wxyz(
        base_quaternion,
        (math.cos(half_angle), 0.0, 0.0, math.sin(half_angle)),
    )
    norm = math.sqrt(sum(component * component for component in result))
    return tuple(component / norm for component in result)  # type: ignore[return-value]


def apply_so101_home_pose(spec: mujoco.MjSpec, pose: Mapping[str, Any]) -> None:
    """Bake a saved pose into both rigid SO101 arm body trees."""
    normalized = validate_so101_home_pose(pose)
    for side in SO101_SIDES:
        for joint_name, angle in normalized[side].items():
            body_part, base_quaternion = SO101_JOINT_BODIES[joint_name]
            body = spec.body(f"cad_{side}_so101_{body_part}_body")
            if body is None:
                raise ValueError(f"Missing SO101 {side} {body_part} body in robot MJCF")
            body.quat = joint_body_quaternion(base_quaternion, angle)


def so101_home_joint_positions(pose: Mapping[str, Any]) -> list[float]:
    """Flatten a dual-arm pose in the deterministic MuJoCo actuator order."""
    normalized = validate_so101_home_pose(pose)
    return [normalized[side][joint_name] for side in SO101_SIDES for joint_name in SO101_ALL_JOINTS]


def configure_articulated_so101(spec: mujoco.MjSpec) -> None:
    """Turn the rigid navigation visuals into two actuated SO101 chains.

    The source URDF's joint frames are already represented by the nested body
    transforms in the reduced MJCF.  Restoring each zero-pose quaternion and
    adding a local Z hinge therefore preserves the calibrated geometry while
    making the links controllable.
    """
    for side in SO101_SIDES:
        for joint_name in SO101_ALL_JOINTS:
            body_part, base_quaternion = SO101_JOINT_BODIES[joint_name]
            body = spec.body(f"cad_{side}_so101_{body_part}_body")
            if body is None:
                raise ValueError(f"Missing SO101 {side} {body_part} body in robot MJCF")
            body.quat = base_quaternion
            # The optimized navigation mesh omits per-link inertials because
            # the arms are rigid.  Small, positive inertials keep the added
            # chains stable without making navigation physics expensive.
            body.mass = 0.08 if joint_name != "gripper" else 0.02
            body.inertia = [1e-4, 1e-4, 1e-4]
            body.explicitinertial = True

            limits = SO101_JOINT_RANGES[joint_name]
            scoped_name = f"{side}_{joint_name}"
            joint = body.add_joint(
                name=scoped_name,
                type=mujoco.mjtJoint.mjJNT_HINGE,
                axis=[0.0, 0.0, 1.0],
            )
            joint.limited = True
            joint.range = limits
            joint.damping = 0.15
            joint.armature = 0.002

            actuator = spec.add_actuator(name=f"{scoped_name}_position", target=scoped_name)
            actuator.trntype = mujoco.mjtTrn.mjTRN_JOINT
            actuator.set_to_position(kp=35.0, kv=3.0)
            actuator.ctrllimited = True
            actuator.ctrlrange = limits
            actuator.forcelimited = True
            actuator.forcerange = [-8.0, 8.0]
