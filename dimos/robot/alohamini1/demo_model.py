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

"""Render AlohaMini1 CAD geometry and virtual views; record the navigation envelope."""

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
from typing import Any

import mujoco
import numpy as np
from PIL import Image as PILImage

from dimos.robot.alohamini1.config import (
    ALOHA_MINI1_NAV_MJCF,
    ALOHA_MINI1_RGB_CAMERAS,
)


def validate(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    scene_path = ALOHA_MINI1_NAV_MJCF.parent / "household_navigation.xml"
    scene = mujoco.MjSpec.from_file(str(scene_path))
    scene.attach(
        mujoco.MjSpec.from_file(str(ALOHA_MINI1_NAV_MJCF)),
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
        "robot": "alohamini1_cad_zero",
        "mjcf_sha256": hashlib.sha256(ALOHA_MINI1_NAV_MJCF.read_bytes()).hexdigest(),
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
        for name, view in [("robot_reference", camera), *[(n, n) for n in ALOHA_MINI1_RGB_CAMERAS]]:
            renderer.update_scene(data, camera=view)
            image = renderer.render().copy()
            path = output / f"{name}.png"
            PILImage.fromarray(image).save(path)
            report["images"].append(
                {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            )
    report["physical_validated"] = False
    report["articulated_manipulation_validated"] = False
    report["cameras_are_virtual"] = True
    report["passed"] = True
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps({"passed": validate(args.output)["passed"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
