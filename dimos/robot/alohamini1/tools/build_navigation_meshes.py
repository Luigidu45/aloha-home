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

"""Build lightweight MuJoCo visual meshes from the AlohaMini1 URDF assets."""

from __future__ import annotations

from pathlib import Path

import open3d as o3d


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
