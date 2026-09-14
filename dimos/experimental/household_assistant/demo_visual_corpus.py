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

"""Render an annotated RGB-only F3 corpus. Annotations never enter the recognizer."""

import argparse
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import time
from typing import Any
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
from PIL import Image as PILImage

from dimos.constants import DIMOS_PROJECT_ROOT

SCENE = DIMOS_PROJECT_ROOT / "dimos/robot/alohamini2/assets/household_navigation.xml"


def render_corpus(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    cases = [
        ("one_bottle", 1, False, False, False, 0.0),
        ("two_bottles", 2, False, False, False, 0.0),
        ("bottle_and_cup", 1, True, False, False, 0.0),
        ("empty_table", 0, False, False, False, 0.0),
        ("cup_only", 0, True, False, False, 0.0),
        ("occluded_bottle", 1, False, True, False, 0.0),
        ("remote_floor", 0, False, False, True, 0.0),
        ("empty_floor", 0, False, False, True, 0.15),
        ("two_bottles_side", 2, False, False, False, 0.25),
        ("one_bottle_side", 1, False, False, False, -0.25),
    ]
    entries: list[dict[str, Any]] = []
    original = ET.parse(SCENE).getroot()
    for case_id, count, cup, occluded, floor, offset in cases:
        scene = copy.deepcopy(original)
        world = scene.find("worldbody")
        assert world is not None
        for body in list(world.findall("body")):
            if body.get("name") in {"bottle_fixture", "remote_fixture"}:
                world.remove(body)
        target_geoms = []
        for i in range(count):
            x = -2.5 + (i - (count - 1) / 2) * 0.32
            body = ET.SubElement(world, "body", pos=f"{x} 1.5 0.75")
            color = "0.10 0.50 0.9 1" if i == 0 else "0.85 0.15 0.1 1"
            names = []
            for part, kind, pos, size, rgba in [
                ("body", "cylinder", "0 0 0.085", "0.04 0.085", color),
                ("shoulder", "ellipsoid", "0 0 0.17", "0.04 0.04 0.025", color),
                ("neck", "cylinder", "0 0 0.195", "0.019 0.025", color),
                ("cap", "cylinder", "0 0 0.225", "0.022 0.009", "0.94 0.94 0.94 1"),
                ("label", "cylinder", "0 0 0.085", "0.0405 0.032", "0.92 0.92 0.94 1"),
            ]:
                name = f"target_{i}_{part}"
                names.append(name)
                ET.SubElement(body, "geom", name=name, type=kind, pos=pos, size=size, rgba=rgba)
            target_geoms.append(names)
        if cup:
            ET.SubElement(
                world,
                "geom",
                type="cylinder",
                pos="-2.2 1.5 0.81",
                size="0.05 0.06",
                rgba="0.95 0.8 0.15 1",
            )
        if occluded:
            ET.SubElement(
                world,
                "geom",
                type="box",
                pos="-2.5 1.25 0.9",
                size="0.15 0.02 0.15",
                rgba="0.4 0.4 0.45 1",
            )
        if floor and case_id == "remote_floor":
            names = ["remote_body"]
            ET.SubElement(
                world,
                "geom",
                name=names[0],
                type="box",
                pos="-3.2 -0.15 0.016",
                size="0.025 0.09 0.015",
                rgba="0.04 0.04 0.05 1",
            )
            for row in range(5):
                for col in range(3):
                    name = f"remote_button_{row}_{col}"
                    names.append(name)
                    ET.SubElement(
                        world,
                        "geom",
                        name=name,
                        type="sphere",
                        pos=f"{-3.216 + col * 0.016} {-0.2 + row * 0.025} .033",
                        size=".004",
                        rgba=".7 .7 .7 1",
                    )
            target_geoms.append(names)
        camera_pos = (
            np.array([-3.2 + offset, -0.8, 0.8]) if floor else np.array([-2.5 + offset, 0.55, 1.25])
        )
        target = np.array([-3.2, -0.15, 0.02]) if floor else np.array([-2.5, 1.5, 0.86])
        z_axis = camera_pos - target
        z_axis /= np.linalg.norm(z_axis)
        x_axis = np.cross([0.0, 0.0, 1.0], z_axis)
        x_axis /= np.linalg.norm(x_axis)
        y_axis = np.cross(z_axis, x_axis)
        ET.SubElement(
            world,
            "camera",
            name="evaluation_camera",
            pos=" ".join(map(str, camera_pos)),
            xyaxes=" ".join(map(str, [*x_axis, *y_axis])),
            fovy="50",
        )
        xml = ET.tostring(scene, encoding="unicode")
        (output / f"{case_id}.xml").write_text(xml)
        model = mujoco.MjModel.from_xml_string(xml)
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        with closing(mujoco.Renderer(model, height=480, width=640)) as renderer:
            renderer.update_scene(data, camera="evaluation_camera")
            rgb = renderer.render().copy()
            renderer.enable_segmentation_rendering()  # type: ignore[attr-defined]  # Missing in MuJoCo stubs.
            renderer.update_scene(data, camera="evaluation_camera")
            segments = renderer.render().copy()
        image_path = output / f"{case_id}.png"
        PILImage.fromarray(rgb).save(image_path)
        boxes = []
        for names in target_geoms:
            ids = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, name) for name in names]
            mask = np.isin(segments[:, :, 0], ids) & (
                segments[:, :, 1] == int(mujoco.mjtObj.mjOBJ_GEOM)
            )
            ys, xs = np.nonzero(mask)
            if len(xs):
                boxes.append([int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1])
        captured = time.time()
        entries.append(
            {
                "id": case_id,
                "image": image_path.name,
                "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                "captured_at": captured,
                "clock_id": "unix",
                "frame_id": "evaluation_camera",
                "origin": "simulation",
                "place_id": "suelo_sala" if floor else "mesa_sala",
                "observer_pose": {
                    "ts": captured,
                    "x": float(camera_pos[0]),
                    "y": float(camera_pos[1]),
                    "yaw": float(np.arctan2(target[1] - camera_pos[1], target[0] - camera_pos[0])),
                    "frame_id": "world",
                },
                "pose_source": "synthetic_fixed_camera_not_robot_odometry",
                "annotation": {
                    "category": "remote_control" if floor else "small_bottle",
                    "visible_boxes": boxes,
                    "occluded": occluded,
                    "physical_count": len(target_geoms),
                    "split": "held_out" if offset else "development",
                },
            }
        )
    manifest = {
        "schema_version": 1,
        "source": "MuJoCo RGB render; synthetic fixtures; no physics or depth claims",
        "annotation_source": "renderer segmentation, evaluation only",
        "scene_sha256": hashlib.sha256(SCENE.read_bytes()).hexdigest(),
        "cases": entries,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    render_corpus(parser.parse_args().output)


if __name__ == "__main__":
    main()
