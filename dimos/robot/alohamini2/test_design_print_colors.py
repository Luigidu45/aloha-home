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

from pathlib import Path

import pytest

from dimos.robot.alohamini2.tools.design_print_colors import (
    build_color_preview_model,
    export_print_manifest,
    hex_to_rgba,
    load_color_scheme,
    rgba_to_hex,
    save_color_scheme,
)


def test_hex_color_roundtrip() -> None:
    assert rgba_to_hex(hex_to_rgba("#3a7fc2")) == "#3a7fc2"
    assert rgba_to_hex(hex_to_rgba("f80")) == "#ff8800"
    with pytest.raises(ValueError, match="formato"):
        hex_to_rgba("#12")


def test_preview_discovers_independent_current_model_meshes() -> None:
    model, pieces = build_color_preview_model()

    assert len(pieces) == 44
    assert len({piece.geom_name for piece in pieces}) == len(pieces)
    assert {piece.group for piece in pieces} == {
        "chassis",
        "left_arm",
        "right_arm",
        "cameras",
        "wheels",
    }
    assert all(int(model.geom_matid[piece.geom_id]) == -1 for piece in pieces)
    assert any(piece.label == "Izq. · Gripper móvil" for piece in pieces)
    assert any(piece.label == "Der. · Gripper móvil" for piece in pieces)


def test_color_scheme_roundtrip_and_csv_export(tmp_path: Path) -> None:
    _model, pieces = build_color_preview_model()
    colors = {piece.geom_name: piece.original_rgba for piece in pieces}
    colors["cad_left_so101_upper_arm_visual"] = hex_to_rgba("#336699")
    scheme_path = tmp_path / "scheme.json"
    manifest_path = tmp_path / "manifest.csv"

    save_color_scheme(scheme_path, pieces, colors)
    loaded = load_color_scheme(scheme_path, {piece.geom_name for piece in pieces})
    export_print_manifest(manifest_path, pieces, loaded)

    assert loaded == colors
    assert rgba_to_hex(loaded["cad_left_so101_upper_arm_visual"]) == "#336699"
    manifest = manifest_path.read_text(encoding="utf-8")
    assert "archivo_stl,color_hex,geom_mujoco" in manifest
    assert "so101_upper_arm_so101_v1.stl,#336699,cad_left_so101_upper_arm_visual" in manifest
