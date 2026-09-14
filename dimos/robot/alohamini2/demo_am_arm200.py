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

"""Render the original robot and verify live simulation RPC articulation control."""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import time
from typing import Any, cast

import mujoco
import numpy as np
from PIL import Image as PILImage

from dimos.core.coordination.module_coordinator import ModuleCoordinator
from dimos.core.global_config import global_config
from dimos.robot.alohamini2.config import (
    ALOHA_MINI2_AM_ARM200_MJCF,
    ALOHA_MINI2_NAV_MJCF,
    ALOHA_MINI2_RGB_CAMERAS,
)
from dimos.robot.alohamini2.sim_module import AlohaMini2SimModule
from dimos.utils.testing.waiting import wait_until


def validate(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    scene_path = ALOHA_MINI2_NAV_MJCF.parent / "household_navigation.xml"
    scene = mujoco.MjSpec.from_file(str(scene_path))
    scene.attach(
        mujoco.MjSpec.from_file(str(ALOHA_MINI2_AM_ARM200_MJCF)),
        prefix="",
        frame=scene.worldbody.add_frame(pos=[-2.5, -1, 0]),
    )
    model = scene.compile()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    points = []
    for i in range(model.ngeom):
        if model.geom_group[i] != 2:
            continue
        mesh = model.geom_dataid[i]
        address = model.mesh_vertadr[mesh]
        count = model.mesh_vertnum[mesh]
        points.append(
            model.mesh_vert[address : address + count] @ data.geom_xmat[i].reshape(3, 3).T
            + data.geom_xpos[i]
            - data.body("base_link").xpos
        )
    vertices = np.vstack(points)
    report: dict[str, Any] = {
        "origin": "simulation",
        "robot": "alohamini2_original_am_arm200",
        "mjcf_sha256": hashlib.sha256(ALOHA_MINI2_AM_ARM200_MJCF.read_bytes()).hexdigest(),
        "zero_pose_bounds_m": [vertices.min(axis=0).tolist(), vertices.max(axis=0).tolist()],
        "zero_pose_radius_m": float(np.linalg.norm(vertices[:, :2], axis=1).max()),
        "images": [],
    }
    camera = mujoco.MjvCamera()  # type: ignore[attr-defined]  # Missing in installed MuJoCo stubs.
    camera.lookat[:] = [-2.5, -1, 0.65]
    camera.distance = 2.3
    camera.azimuth = 135
    camera.elevation = -18
    with closing(mujoco.Renderer(model, height=480, width=640)) as renderer:
        for name, view in [("robot_reference", camera), *[(n, n) for n in ALOHA_MINI2_RGB_CAMERAS]]:
            renderer.update_scene(data, camera=view)
            image = renderer.render().copy()
            path = output / f"{name}.png"
            PILImage.fromarray(image).save(path)
            report["images"].append(
                {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            )
    global_config.update(viewer="none", transport="zenoh", simulation="mujoco")
    coordinator = ModuleCoordinator()
    try:
        coordinator.start()
        coordinator.load_blueprint(
            AlohaMini2SimModule.blueprint(
                robot_mjcf=ALOHA_MINI2_AM_ARM200_MJCF,
                scene_xml=scene_path,
                spawn_xy=(-2.5, -1),
                spawn_z=0,
                arm_model="am_arm200",
                dof=15,
                planar_base_height=0.005,
                headless=True,
                camera_name="front_camera",
                enable_color=False,
                enable_depth=False,
                enable_pointcloud=False,
                additional_camera_names=[],
            ).global_config(n_workers=0)
        )
        sim = cast("AlohaMini2SimModule", coordinator.get_instance(AlohaMini2SimModule))
        initial = sim.get_sim_joint_state()
        assert len(initial) == 15
        targets = {name: 0.0 for name in initial}
        for name in targets:
            local = name.lstrip("/")
            if local == "vertical_move":
                targets[name] = 0.05
            elif local in {"left_wrist_roll", "left_gripper", "right_gripper"}:
                targets[name] = 0.15
            elif local == "right_wrist_roll":
                targets[name] = -0.15
        started = time.monotonic()
        assert sim.set_sim_joint_positions(targets)

        def reached() -> bool:
            state = sim.get_sim_joint_state()
            return all(abs(state[name] - target) < 0.025 for name, target in targets.items())

        wait_until(reached, timeout=10, interval=0.05)
        report["joint_targets"] = targets
        report["joint_positions"] = sim.get_sim_joint_state()
        report["target_latency_s"] = time.monotonic() - started
        assert sim.reset()
        wait_until(
            lambda: all(abs(v) < 0.025 for v in sim.get_sim_joint_state().values()),
            timeout=5,
            interval=0.05,
        )
        report["reset_positions"] = sim.get_sim_joint_state()
        report["passed"] = True
    finally:
        coordinator.stop()
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps({"passed": validate(args.output)["passed"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
