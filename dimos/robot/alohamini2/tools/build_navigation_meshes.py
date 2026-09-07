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

"""Build lightweight MuJoCo visual meshes from the AlohaMini2 URDF assets."""

from __future__ import annotations

import argparse
from pathlib import Path

import open3d as o3d

SOURCE_MESHES: dict[str, int] = {
    "base_link.STL": 20_000,
    "vertical_link.STL": 12_000,
    "chest_camera.STL": 3_342,
    "Link2_dp.STL": 12_000,
    "Link3_dp.STL": 12_000,
    "Link4_dp.STL": 12_000,
    "back_camera.STL": 3_342,
    "front_camera.STL": 3_342,
    "left_Base.STL": 12_000,
    "left_Rotation_Pitch.STL": 12_000,
    "left_Upper_Arm.STL": 12_000,
    "left_Lower_Arm.STL": 12_000,
    "left_Wrist_Pitch_Roll.STL": 3_176,
    "left_wrist_yaw.STL": 12_000,
    "left_Fixed_Jaw.STL": 4_020,
    "left_Moving_Jaw.STL": 1_522,
    "left_camera.STL": 3_141,
}

SO101_SOURCE_MESHES: dict[str, int] = {
    "base_motor_holder_so101_v1.stl": 5_000,
    "base_so101_v2.stl": 3_000,
    "motor_holder_so101_base_v1.stl": 4_000,
    "motor_holder_so101_wrist_v1.stl": 4_000,
    "moving_jaw_so101_v1.stl": 4_000,
    "rotation_pitch_so101_v1.stl": 4_000,
    "sts3215_03a_no_horn_v1.stl": 4_000,
    "sts3215_03a_v1.stl": 4_000,
    "under_arm_so101_v1.stl": 5_000,
    "upper_arm_so101_v1.stl": 5_000,
    "waveshare_mounting_plate_so101_v2.stl": 1_254,
    "wrist_roll_follower_so101_v1.stl": 4_000,
    "wrist_roll_pitch_so101_v2.stl": 5_000,
}


def build_mesh(source: Path, destination: Path, target_triangles: int) -> tuple[int, int]:
    """Clean and decimate one STL, returning input and output triangle counts."""
    mesh = o3d.io.read_triangle_mesh(str(source), enable_post_processing=False)
    if mesh.is_empty():
        raise ValueError(f"Could not read mesh: {source}")

    input_triangles = len(mesh.triangles)
    mesh.remove_duplicated_vertices()
    mesh.remove_duplicated_triangles()
    mesh.remove_degenerate_triangles()
    mesh.remove_unreferenced_vertices()
    if len(mesh.triangles) > target_triangles:
        mesh = mesh.simplify_quadric_decimation(target_number_of_triangles=target_triangles)
    mesh.compute_triangle_normals()

    destination.parent.mkdir(parents=True, exist_ok=True)
    if not o3d.io.write_triangle_mesh(
        str(destination),
        mesh,
        write_ascii=False,
        compressed=False,
        write_vertex_normals=False,
        write_vertex_colors=False,
    ):
        raise RuntimeError(f"Could not write mesh: {destination}")
    return input_triangles, len(mesh.triangles)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path, help="Directory containing the URDF STL files")
    parser.add_argument("output_dir", type=Path, help="Destination for optimized STL files")
    parser.add_argument(
        "--so101-source-dir",
        type=Path,
        help="Optional directory containing the SO101 STL files",
    )
    parser.add_argument(
        "--so101-only",
        action="store_true",
        help="Skip the original AlohaMini2 meshes and only build SO101 assets",
    )
    args = parser.parse_args()

    if not args.so101_only:
        for filename, target_triangles in SOURCE_MESHES.items():
            input_count, output_count = build_mesh(
                args.source_dir / filename,
                args.output_dir / filename.lower(),
                target_triangles,
            )
            print(f"{filename}: {input_count} -> {output_count} triangles")

    if args.so101_source_dir is not None:
        for filename, target_triangles in SO101_SOURCE_MESHES.items():
            input_count, output_count = build_mesh(
                args.so101_source_dir / filename,
                args.output_dir / f"so101_{filename}",
                target_triangles,
            )
            print(f"SO101 {filename}: {input_count} -> {output_count} triangles")


if __name__ == "__main__":
    main()
