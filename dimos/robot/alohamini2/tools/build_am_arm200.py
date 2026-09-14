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

"""Convert the supplied original AlohaMini2 URDF into a portable articulated MJCF.

CAD frames, axes and inertias are retained. Servo gains, base skid and sensors
are simulation assumptions; the manifest records them separately from the URDF.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial.transform import Rotation

from dimos.robot.alohamini2.tools.build_navigation_meshes import build_mesh


def numbers(values: Any) -> str:
    return " ".join(format(float(x), ".12g") for x in values)


def required(element: ET.Element, path: str) -> ET.Element:
    child = element.find(path)
    if child is None:
        raise ValueError(f"missing URDF element: {path}")
    return child


def sub(parent: ET.Element, tag: str, **attributes: str) -> ET.Element:
    return ET.SubElement(parent, tag, attributes)


def origin(element: ET.Element | None) -> dict[str, str]:
    if element is None:
        return {}
    xyz = element.get("xyz", "0 0 0")
    rpy = [float(v) for v in element.get("rpy", "0 0 0").split()]
    x, y, z, w = Rotation.from_euler("xyz", rpy).as_quat()
    return {"pos": xyz, "quat": numbers([w, x, y, z])}


def build(source: Path, output: Path) -> None:
    urdf_path = source / "urdf" / "alohamini2.urdf"
    urdf = ET.parse(urdf_path).getroot()
    if urdf.get("name") != "alohamini2_urdf":
        raise ValueError("expected original alohamini2_urdf, not Pro or SO101")
    output.mkdir(parents=True, exist_ok=True)
    (output / "source.urdf").write_text(
        "\n".join(line.rstrip() for line in urdf_path.read_text().splitlines()) + "\n"
    )
    manifest: dict[str, Any] = {
        "source_sha256": hashlib.sha256(urdf_path.read_bytes()).hexdigest(),
        "robot": urdf.get("name"),
        "mesh_conversion": [],
        "joint_order": [],
        "physical_validated": False,
        "assumptions": [
            "CAD +X lateral/-Y forward rotated +90 deg about Z into DimOS frame",
            "free root constrained by existing holonomic driver; wheels fixed as in URDF",
            "joint zero is simulation reference, not hardware home or loaded_home",
            "servo gains/forces/damping are simulation parameters, not URDF actuator limits",
            "convex arm collisions; base envelope/skid approximate",
            "camera optical orientations follow existing CAD camera convention; mounting/intrinsics not calibrated",
            "nav ray cameras approximate coverage, not a Unitree L2 sensor model",
        ],
    }
    mj = ET.Element("mujoco", model="alohamini2_am_arm200")
    sub(mj, "compiler", angle="radian", autolimits="true")
    sub(mj, "option", timestep="0.005", integrator="implicitfast", gravity="0 0 -9.81")
    visual = sub(mj, "visual")
    sub(visual, "headlight", ambient=".5 .5 .5", diffuse=".7 .7 .7")
    sub(visual, "map", znear=".0002")
    assets = sub(mj, "asset")
    links = {link.get("name"): link for link in urdf.findall("link")}
    children: dict[str, list[ET.Element]] = {}
    for joint in urdf.findall("joint"):
        children.setdefault(required(joint, "parent").attrib["link"], []).append(joint)
    mesh_names = {}
    for mesh in urdf.iter("mesh"):
        filename = Path(mesh.attrib["filename"]).name
        if filename in mesh_names:
            continue
        src = source / "alohamini2_meshes" / filename
        dst = output / "meshes" / filename.lower()
        before, after = build_mesh(src, dst, 5000)
        name = Path(filename).stem
        mesh_names[filename] = name
        sub(assets, "mesh", name=name, file=f"meshes/{dst.name}")
        manifest["mesh_conversion"].append(
            {
                "file": filename,
                "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                "output_sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
                "input_triangles": before,
                "output_triangles": after,
            }
        )
    world = sub(mj, "worldbody")
    base = sub(world, "body", name="base_link", pos="0 0 0.005")
    sub(base, "freejoint", name="root")
    # Fixed carrier holds the exact original CAD frame below the DimOS base.
    cad = sub(base, "body", name="cad_base", quat="0.707106781186548 0 0 0.707106781186548")
    sub(
        base,
        "geom",
        name="base_collision",
        type="box",
        pos="0 0 .18",
        size=".22 .23 .12",
        rgba="0 0 0 0",
        group="3",
        mass="0",
    )
    sub(
        base,
        "geom",
        name="ground_skid_collision",
        type="box",
        pos="0 0 .026",
        size=".17 .17 .031",
        friction=".05 .01 .001",
        rgba="0 0 0 0",
        group="3",
        mass="0",
    )
    sub(
        base,
        "geom",
        name="tower_collision",
        type="box",
        pos="-.075 0 .7",
        size=".08 .10 .4",
        rgba="0 0 0 0",
        group="3",
        mass="0",
    )
    contacts = sub(mj, "contact")
    for side in ("left", "right"):
        sub(contacts, "exclude", body1=f"{side}_wrist_yaw", body2=f"{side}_Moving_Jaw")
    manifest["collision_exclusions"] = [
        f"{side}_wrist_yaw / {side}_Moving_Jaw: convex housing overlaps its own jaw at CAD zero"
        for side in ("left", "right")
    ]
    actuators = sub(mj, "actuator")

    def add_link(name: str, body: ET.Element) -> None:
        link = links[name]
        inertial = link.find("inertial")
        if inertial is not None:
            mass = float(required(inertial, "mass").attrib["value"])
            if mass > 0:
                vals = required(inertial, "inertia").attrib
                tensor = np.array(
                    [
                        [float(vals["ixx"]), float(vals["ixy"]), float(vals["ixz"])],
                        [float(vals["ixy"]), float(vals["iyy"]), float(vals["iyz"])],
                        [float(vals["ixz"]), float(vals["iyz"]), float(vals["izz"])],
                    ]
                )
                frame = inertial.find("origin")
                angles = (
                    [float(x) for x in frame.get("rpy", "0 0 0").split()]
                    if frame is not None
                    else [0.0, 0.0, 0.0]
                )
                rot = Rotation.from_euler("xyz", angles).as_matrix()
                tensor = rot @ tensor @ rot.T
                sub(
                    body,
                    "inertial",
                    pos=frame.get("xyz", "0 0 0") if frame is not None else "0 0 0",
                    mass=str(mass),
                    fullinertia=numbers(
                        [
                            tensor[0, 0],
                            tensor[1, 1],
                            tensor[2, 2],
                            tensor[0, 1],
                            tensor[0, 2],
                            tensor[1, 2],
                        ]
                    ),
                )
        for index, v in enumerate(link.findall("visual")):
            mesh = v.find("geometry/mesh")
            if mesh is None:
                raise ValueError("original model requires mesh visuals")
            mesh_name = mesh_names[Path(mesh.attrib["filename"]).name]
            color = v.find("material/color")
            rgba = color.attrib["rgba"] if color is not None else ".7 .72 .75 1"
            sub(
                body,
                "geom",
                name=f"visual_{name}_{index}",
                type="mesh",
                mesh=mesh_name,
                rgba=rgba,
                contype="0",
                conaffinity="0",
                group="2",
                mass="0",
                **origin(v.find("origin")),
            )
            if name.startswith(("left_", "right_")) and "camera" not in name:
                sub(
                    body,
                    "geom",
                    name=f"collision_{name}_{index}",
                    type="mesh",
                    mesh=mesh_name,
                    rgba="0 0 0 0",
                    group="3",
                    mass="0",
                    **origin(v.find("origin")),
                )
        if name in ("front_camera", "back_camera", "chest_camera", "left_camera", "right_camera"):
            optical = (
                {"quat": "0 1 0 0"}
                if name in {"left_camera", "right_camera"}
                else {"xyaxes": "0 -1 0 -1 0 0"}
            )
            sub(body, "camera", name=name, pos="0 0 .025", fovy="69", **optical)
        if name.endswith("Fixed_Jaw"):
            sub(
                body,
                "site",
                name=name.split("_")[0] + "_tool",
                pos="0 0 0",
                size=".007",
                rgba="0 1 0 1",
                group="4",
            )
        for joint in children.get(name, []):
            child = required(joint, "child").attrib["link"]
            node = sub(body, "body", name=child, **origin(joint.find("origin")))
            kind = joint.attrib["type"]
            if kind != "fixed":
                joint_name = joint.attrib["name"]
                limit = required(joint, "limit")
                bounds = f"{limit.attrib['lower']} {limit.attrib['upper']}"
                sub(
                    node,
                    "joint",
                    name=joint_name,
                    type="slide" if kind == "prismatic" else "hinge",
                    axis=required(joint, "axis").attrib["xyz"],
                    range=bounds,
                    damping="10" if kind == "prismatic" else "1",
                    armature=".01",
                )
                sub(
                    actuators,
                    "position",
                    name=joint_name + "_position",
                    joint=joint_name,
                    kp="4000" if kind == "prismatic" else "120",
                    kv="200" if kind == "prismatic" else "8",
                    ctrlrange=bounds,
                    forcerange="-500 500" if kind == "prismatic" else "-40 40",
                )
                manifest["joint_order"].append(joint_name)
            add_link(child, node)

    add_link("base_link", cad)
    for name, pos, axes in [
        ("nav_front", ".24 0 .58", "0 -1 0 0 0 1"),
        ("nav_left", "0 .25 .58", "1 0 0 0 0 1"),
        ("nav_back", "-.24 0 .58", "0 1 0 0 0 1"),
        ("nav_right", "0 -.25 .58", "-1 0 0 0 0 1"),
    ]:
        sub(base, "camera", name=name, pos=pos, xyaxes=axes, fovy="90")
    ET.indent(mj)
    (output / "robot.xml").write_text(ET.tostring(mj, encoding="unicode") + "\n")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.source, args.output)


if __name__ == "__main__":
    main()
