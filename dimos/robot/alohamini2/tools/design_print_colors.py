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

"""Interactive print-color designer for the current AlohaMini2-SO101 model."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import partial
import json
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Any
import xml.etree.ElementTree as ET

import mujoco
import mujoco.viewer

from dimos.robot.alohamini2.config import (
    ALOHA_MINI2_COLOR_SCHEME,
    ALOHA_MINI2_NAV_MJCF,
    ALOHA_MINI2_SO101_HOME,
)
from dimos.robot.alohamini2.so101_home import apply_so101_home_pose, load_so101_home_pose

RGBA = tuple[float, float, float, float]

PRESET_COLORS: tuple[tuple[str, str], ...] = (
    ("Negro", "#17191d"),
    ("Blanco", "#e6e8eb"),
    ("Gris", "#777d87"),
    ("Rojo", "#d9363e"),
    ("Naranja", "#ef7d22"),
    ("Amarillo", "#ffd11a"),
    ("Verde", "#36a852"),
    ("Azul", "#2f6fdb"),
    ("Morado", "#844fc1"),
)

GROUP_LABELS = {
    "chassis": "Chasis y torre",
    "left_arm": "Brazo SO101 izquierdo",
    "right_arm": "Brazo SO101 derecho",
    "cameras": "Cámaras",
    "wheels": "Ruedas",
}


@dataclass(frozen=True, slots=True)
class MeshPiece:
    """One independently colorable mesh instance in the MuJoCo model."""

    geom_id: int
    geom_name: str
    mesh_name: str
    stl_file: str
    group: str
    label: str
    original_rgba: RGBA


def rgba_to_hex(rgba: RGBA) -> str:
    """Convert a normalized RGB(A) color to a Tk-compatible hexadecimal color."""
    channels = [round(min(max(channel, 0.0), 1.0) * 255) for channel in rgba[:3]]
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def hex_to_rgba(value: str, alpha: float = 1.0) -> RGBA:
    """Parse #RGB or #RRGGBB into normalized RGBA."""
    normalized = value.strip().lower()
    if normalized.startswith("#"):
        normalized = normalized[1:]
    if len(normalized) == 3:
        normalized = "".join(character * 2 for character in normalized)
    if len(normalized) != 6:
        raise ValueError("El color debe usar el formato #RRGGBB o #RGB")
    try:
        channels = tuple(int(normalized[index : index + 2], 16) / 255 for index in (0, 2, 4))
    except ValueError as error:
        raise ValueError("El color contiene caracteres no hexadecimales") from error
    return (channels[0], channels[1], channels[2], min(max(alpha, 0.0), 1.0))


def _mesh_files(mjcf_path: Path) -> dict[str, str]:
    root = ET.parse(mjcf_path).getroot()
    return {
        element.attrib["name"]: element.attrib["file"]
        for element in root.findall("./asset/mesh")
        if "name" in element.attrib and "file" in element.attrib
    }


def _piece_group(geom_name: str) -> str:
    if "camera" in geom_name:
        return "cameras"
    if "wheel" in geom_name:
        return "wheels"
    if "left_so101" in geom_name:
        return "left_arm"
    if "right_so101" in geom_name:
        return "right_arm"
    return "chassis"


def _piece_label(geom_name: str) -> str:
    name = geom_name.removeprefix("cad_").removesuffix("_visual")
    side = ""
    if name.startswith("left_so101_"):
        side = "Izq. · "
        name = name.removeprefix("left_so101_")
    elif name.startswith("right_so101_"):
        side = "Der. · "
        name = name.removeprefix("right_so101_")
    translations = {
        "base_link": "Base móvil",
        "vertical_link": "Torre vertical",
        "chest_camera": "Cámara de pecho",
        "left_camera": "Cámara wrist izquierda",
        "right_camera": "Cámara wrist derecha",
        "front_camera": "Cámara frontal",
        "back_camera": "Cámara posterior",
        "base_holder": "Soporte del motor base",
        "base": "Base",
        "base_servo": "Servo de base",
        "mounting_plate": "Placa de montaje",
        "shoulder_servo": "Servo del hombro",
        "motor_holder_base": "Soporte motor del hombro",
        "rotation_pitch": "Soporte de rotación",
        "upper_arm_servo": "Servo del brazo superior",
        "upper_arm": "Brazo superior",
        "under_arm": "Antebrazo",
        "motor_holder_wrist": "Soporte motor de muñeca",
        "lower_arm_servo": "Servo del antebrazo",
        "wrist_servo": "Servo de muñeca",
        "wrist_roll_pitch": "Soporte wrist roll/pitch",
        "gripper_servo": "Servo del gripper",
        "wrist_roll_follower": "Gripper fijo / follower",
        "moving_jaw": "Gripper móvil",
    }
    if name.startswith("wheel_"):
        return f"Rueda {name.removeprefix('wheel_')}"
    return side + translations.get(name, name.replace("_", " ").capitalize())


def build_color_preview_model() -> tuple[mujoco.MjModel, list[MeshPiece]]:
    """Build the current rigid-home model and make every mesh color independent."""
    spec = mujoco.MjSpec.from_file(str(ALOHA_MINI2_NAV_MJCF))
    apply_so101_home_pose(spec, load_so101_home_pose(ALOHA_MINI2_SO101_HOME))
    model = spec.compile()
    mesh_files = _mesh_files(ALOHA_MINI2_NAV_MJCF)
    pieces: list[MeshPiece] = []

    for geom_id in range(model.ngeom):
        if model.geom_type[geom_id] != mujoco.mjtGeom.mjGEOM_MESH:
            continue
        geom_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, geom_id)
        mesh_id = int(model.geom_dataid[geom_id])
        mesh_name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_MESH, mesh_id)
        if geom_name is None or mesh_name is None:
            continue

        material_id = int(model.geom_matid[geom_id])
        source_rgba = model.mat_rgba[material_id] if material_id >= 0 else model.geom_rgba[geom_id]
        original_rgba: RGBA = tuple(float(channel) for channel in source_rgba)  # type: ignore[assignment]
        # A shared material would recolor every occurrence at once. Detach it so
        # each physical STL instance can be explored independently.
        model.geom_matid[geom_id] = -1
        model.geom_rgba[geom_id] = original_rgba
        pieces.append(
            MeshPiece(
                geom_id=geom_id,
                geom_name=geom_name,
                mesh_name=mesh_name,
                stl_file=mesh_files.get(mesh_name, f"{mesh_name}.stl"),
                group=_piece_group(geom_name),
                label=_piece_label(geom_name),
                original_rgba=original_rgba,
            )
        )
    return model, pieces


def save_color_scheme(path: Path, pieces: list[MeshPiece], colors: dict[str, RGBA]) -> None:
    """Atomically save a printable per-instance color scheme."""
    payload = {
        "version": 1,
        "model": "alohamini2-so101",
        "pieces": {
            piece.geom_name: {
                "label": piece.label,
                "stl": piece.stl_file,
                "hex": rgba_to_hex(colors[piece.geom_name]),
                "rgba": list(colors[piece.geom_name]),
            }
            for piece in pieces
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary_path.replace(path)


def load_color_scheme(path: Path, valid_names: set[str]) -> dict[str, RGBA]:
    """Load and validate colors for mesh instances present in the current model."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("El archivo no es un diseño de color AlohaMini2 compatible")
    raw_pieces = payload.get("pieces")
    if not isinstance(raw_pieces, dict):
        raise ValueError("El diseño no contiene la sección 'pieces'")

    colors: dict[str, RGBA] = {}
    for geom_name, raw_piece in raw_pieces.items():
        if geom_name not in valid_names or not isinstance(raw_piece, dict):
            continue
        raw_rgba = raw_piece.get("rgba")
        if not isinstance(raw_rgba, list) or len(raw_rgba) != 4:
            raise ValueError(f"Color RGBA inválido para {geom_name}")
        rgba = tuple(float(channel) for channel in raw_rgba)
        if any(channel < 0.0 or channel > 1.0 for channel in rgba):
            raise ValueError(f"Color fuera del rango 0..1 para {geom_name}")
        colors[geom_name] = rgba  # type: ignore[assignment]
    return colors


def export_print_manifest(path: Path, pieces: list[MeshPiece], colors: dict[str, RGBA]) -> None:
    """Export a spreadsheet-friendly list of every physical mesh occurrence."""
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(("grupo", "pieza", "archivo_stl", "color_hex", "geom_mujoco"))
        for piece in pieces:
            writer.writerow(
                (
                    GROUP_LABELS[piece.group],
                    piece.label,
                    piece.stl_file,
                    rgba_to_hex(colors[piece.geom_name]),
                    piece.geom_name,
                )
            )


class AlohaMini2ColorDesigner:
    """Tk color controls synchronized with a passive MuJoCo preview."""

    def __init__(
        self,
        model: mujoco.MjModel,
        data: mujoco.MjData,
        viewer: Any,
        pieces: list[MeshPiece],
    ) -> None:
        self._model = model
        self._data = data
        self._viewer = viewer
        self._pieces = pieces
        self._by_name = {piece.geom_name: piece for piece in pieces}
        self._colors = {piece.geom_name: piece.original_rgba for piece in pieces}
        self._root = tk.Tk()
        self._root.title("AlohaMini2-SO101 — diseñador de colores para impresión 3D")
        self._root.geometry("1120x720")
        self._root.minsize(900, 600)
        self._root.protocol("WM_DELETE_WINDOW", self._close)
        self._search = tk.StringVar()
        self._hex_color = tk.StringVar(value="#ffd11a")
        self._link_same_stl = tk.BooleanVar(value=False)
        self._link_mirror = tk.BooleanVar(value=True)
        self._status = tk.StringVar(value=f"{len(pieces)} piezas STL listas para colorear.")
        self._tree: ttk.Treeview
        self._color_sample: tk.Label
        self._build_controls()
        self._search.trace_add("write", self._on_search_change)
        self._populate_tree()
        self._load_default_if_present()
        self._root.after(16, self._refresh_viewer)

    def _on_search_change(self, *_args: str) -> None:
        self._populate_tree()

    def _build_controls(self) -> None:
        outer = ttk.Frame(self._root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=3)
        outer.columnconfigure(1, weight=2)
        outer.rowconfigure(1, weight=1)

        ttk.Label(
            outer,
            text=(
                "Selecciona una o varias piezas. El color se actualiza en MuJoCo en tiempo real; "
                "Ctrl/Shift permite selección múltiple."
            ),
            wraplength=1050,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        browser = ttk.LabelFrame(outer, text="Piezas del modelo actual", padding=8)
        browser.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        browser.columnconfigure(0, weight=1)
        browser.rowconfigure(1, weight=1)
        ttk.Entry(browser, textvariable=self._search).grid(
            row=0, column=0, sticky="ew", pady=(0, 8)
        )
        self._tree = ttk.Treeview(
            browser,
            columns=("stl", "color"),
            displaycolumns=("stl", "color"),
            selectmode="extended",
        )
        self._tree.heading("#0", text="Pieza")
        self._tree.heading("stl", text="Archivo STL")
        self._tree.heading("color", text="Color")
        self._tree.column("#0", width=245)
        self._tree.column("stl", width=260)
        self._tree.column("color", width=80, anchor="center")
        scrollbar = ttk.Scrollbar(browser, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        self._tree.bind("<<TreeviewSelect>>", self._on_selection)

        controls = ttk.LabelFrame(outer, text="Color y vínculos", padding=12)
        controls.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        controls.columnconfigure(1, weight=1)

        ttk.Label(controls, text="Color hexadecimal").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self._hex_color, width=12).grid(
            row=0, column=1, sticky="ew", padx=8
        )
        self._color_sample = tk.Label(controls, width=5, relief=tk.SUNKEN, bg=self._hex_color.get())
        self._color_sample.grid(row=0, column=2, sticky="e")
        ttk.Button(controls, text="Elegir…", command=self._choose_color).grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(8, 4)
        )
        ttk.Button(controls, text="APLICAR A SELECCIÓN", command=self._apply_entry_color).grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=4
        )

        palette = ttk.LabelFrame(controls, text="Colores rápidos", padding=6)
        palette.grid(row=3, column=0, columnspan=3, sticky="ew", pady=10)
        for index, (name, color) in enumerate(PRESET_COLORS):
            button = tk.Button(
                palette,
                text=name,
                bg=color,
                fg="#ffffff" if sum(hex_to_rgba(color)[:3]) < 1.45 else "#000000",
                command=partial(self._apply_color, color),
                width=10,
            )
            button.grid(row=index // 3, column=index % 3, padx=2, pady=2, sticky="ew")
            palette.columnconfigure(index % 3, weight=1)

        ttk.Checkbutton(
            controls,
            text="Aplicar también a todas las instancias del mismo STL",
            variable=self._link_same_stl,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=3)
        ttk.Checkbutton(
            controls,
            text="Aplicar también a la pieza simétrica izquierda/derecha",
            variable=self._link_mirror,
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=3)

        ttk.Button(controls, text="Identificar pieza", command=self._flash_selection).grid(
            row=6, column=0, columnspan=3, sticky="ew", pady=(12, 3)
        )
        ttk.Button(controls, text="Restaurar selección", command=self._reset_selection).grid(
            row=7, column=0, columnspan=3, sticky="ew", pady=3
        )
        ttk.Button(controls, text="Restaurar todo", command=self._reset_all).grid(
            row=8, column=0, columnspan=3, sticky="ew", pady=3
        )

        files = ttk.Frame(outer)
        files.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(files, text="GUARDAR DISEÑO", command=self._save_default).pack(side=tk.LEFT)
        ttk.Button(files, text="Guardar como…", command=self._save_as).pack(side=tk.LEFT, padx=4)
        ttk.Button(files, text="Cargar…", command=self._load_from_dialog).pack(side=tk.LEFT, padx=4)
        ttk.Button(files, text="Exportar lista CSV…", command=self._export_csv).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Label(outer, textvariable=self._status, wraplength=1050).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )

    def _populate_tree(self) -> None:
        selected = set(self._selected_names()) if hasattr(self, "_tree") else set()
        self._tree.delete(*self._tree.get_children())
        query = self._search.get().strip().lower()
        for group, group_label in GROUP_LABELS.items():
            matching = [
                piece
                for piece in self._pieces
                if piece.group == group
                and (
                    not query
                    or query in f"{piece.label} {piece.stl_file} {piece.geom_name}".lower()
                )
            ]
            if not matching:
                continue
            self._tree.insert("", tk.END, iid=group, text=group_label, open=True)
            for piece in matching:
                color = rgba_to_hex(self._colors[piece.geom_name])
                self._tree.insert(
                    group,
                    tk.END,
                    iid=piece.geom_name,
                    text=piece.label,
                    values=(Path(piece.stl_file).name, color),
                )
        restorable = [name for name in selected if self._tree.exists(name)]
        if restorable:
            self._tree.selection_set(restorable)

    def _selected_names(self) -> list[str]:
        return [item for item in self._tree.selection() if item in self._by_name]

    def _expanded_selection(self) -> set[str]:
        selected = set(self._selected_names())
        if self._link_mirror.get():
            for name in tuple(selected):
                if "_left_" in name:
                    mirror = name.replace("_left_", "_right_", 1)
                elif "_right_" in name:
                    mirror = name.replace("_right_", "_left_", 1)
                else:
                    continue
                if mirror in self._by_name:
                    selected.add(mirror)
        if self._link_same_stl.get():
            mesh_names = {self._by_name[name].mesh_name for name in selected}
            selected.update(
                piece.geom_name for piece in self._pieces if piece.mesh_name in mesh_names
            )
        return selected

    def _on_selection(self, _event: tk.Event[tk.Misc]) -> None:
        names = self._selected_names()
        if len(names) == 1:
            color = rgba_to_hex(self._colors[names[0]])
            self._hex_color.set(color)
            self._color_sample.configure(bg=color)
            piece = self._by_name[names[0]]
            self._status.set(f"Seleccionada: {piece.label} · {piece.stl_file}")
        elif names:
            self._status.set(f"{len(names)} piezas seleccionadas.")

    def _choose_color(self) -> None:
        result = colorchooser.askcolor(
            self._hex_color.get(), parent=self._root, title="Color de pieza"
        )
        if result[1] is not None:
            self._apply_color(result[1])

    def _apply_entry_color(self) -> None:
        self._apply_color(self._hex_color.get())

    def _apply_color(self, color: str) -> None:
        try:
            rgba = hex_to_rgba(color)
        except ValueError as error:
            messagebox.showerror("Color inválido", str(error), parent=self._root)
            return
        targets = self._expanded_selection()
        if not targets:
            self._status.set("Selecciona al menos una pieza antes de aplicar un color.")
            return
        self._set_colors({name: rgba for name in targets})
        normalized = rgba_to_hex(rgba)
        self._hex_color.set(normalized)
        self._color_sample.configure(bg=normalized)
        self._status.set(f"Color {normalized} aplicado a {len(targets)} pieza(s).")

    def _set_colors(self, colors: dict[str, RGBA]) -> None:
        with self._viewer.lock():
            for name, rgba in colors.items():
                piece = self._by_name[name]
                self._model.geom_rgba[piece.geom_id] = rgba
                self._colors[name] = rgba
        self._populate_tree()

    def _flash_selection(self) -> None:
        names = self._selected_names()
        if not names:
            self._status.set("Selecciona una pieza para identificarla.")
            return
        saved = {name: self._colors[name] for name in names}
        with self._viewer.lock():
            for name in names:
                self._model.geom_rgba[self._by_name[name].geom_id] = (1.0, 0.0, 1.0, 1.0)

        def restore() -> None:
            if not self._root.winfo_exists():
                return
            with self._viewer.lock():
                for name, rgba in saved.items():
                    self._model.geom_rgba[self._by_name[name].geom_id] = rgba

        self._root.after(900, restore)
        self._status.set("La selección parpadeará en magenta durante un instante.")

    def _reset_selection(self) -> None:
        targets = self._expanded_selection()
        if not targets:
            self._status.set("Selecciona al menos una pieza para restaurarla.")
            return
        self._set_colors({name: self._by_name[name].original_rgba for name in targets})
        self._status.set(f"Se restauraron {len(targets)} pieza(s).")

    def _reset_all(self) -> None:
        self._set_colors({piece.geom_name: piece.original_rgba for piece in self._pieces})
        self._status.set("Se restauraron los colores originales del modelo.")

    def _save(self, path: Path) -> None:
        try:
            save_color_scheme(path, self._pieces, self._colors)
        except OSError as error:
            messagebox.showerror("No se pudo guardar", str(error), parent=self._root)
            return
        self._status.set(f"Diseño guardado en {path}")

    def _save_default(self) -> None:
        self._save(ALOHA_MINI2_COLOR_SCHEME)

    def _save_as(self) -> None:
        filename = filedialog.asksaveasfilename(
            parent=self._root,
            title="Guardar combinación de colores",
            defaultextension=".json",
            filetypes=(("Diseño JSON", "*.json"),),
            initialfile=ALOHA_MINI2_COLOR_SCHEME.name,
        )
        if filename:
            self._save(Path(filename))

    def _load_default_if_present(self) -> None:
        if ALOHA_MINI2_COLOR_SCHEME.exists():
            self._load(ALOHA_MINI2_COLOR_SCHEME)

    def _load_from_dialog(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self._root,
            title="Cargar combinación de colores",
            filetypes=(("Diseño JSON", "*.json"), ("Todos", "*")),
        )
        if filename:
            self._load(Path(filename))

    def _load(self, path: Path) -> None:
        try:
            colors = load_color_scheme(path, set(self._by_name))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror("No se pudo cargar", str(error), parent=self._root)
            return
        self._set_colors(colors)
        self._status.set(f"Se cargaron {len(colors)} colores desde {path}")

    def _export_csv(self) -> None:
        filename = filedialog.asksaveasfilename(
            parent=self._root,
            title="Exportar lista de piezas para impresión",
            defaultextension=".csv",
            filetypes=(("CSV", "*.csv"),),
            initialfile="alohamini2_colores_impresion.csv",
        )
        if not filename:
            return
        try:
            export_print_manifest(Path(filename), self._pieces, self._colors)
        except OSError as error:
            messagebox.showerror("No se pudo exportar", str(error), parent=self._root)
            return
        self._status.set(f"Lista de impresión exportada en {filename}")

    def _refresh_viewer(self) -> None:
        if not self._viewer.is_running():
            self._close()
            return
        self._viewer.sync()
        self._root.after(16, self._refresh_viewer)

    def _close(self) -> None:
        if self._root.winfo_exists():
            self._root.destroy()

    def run(self) -> None:
        """Run until either the controls or MuJoCo preview is closed."""
        self._root.mainloop()


def launch_alohamini2_color_designer() -> None:
    """Open the current AlohaMini2-SO101 model and per-piece color controls."""
    model, pieces = build_color_preview_model()
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    with mujoco.viewer.launch_passive(model, data) as viewer:
        viewer.cam.lookat[:] = (0.0, 0.0, 0.55)
        viewer.cam.distance = 1.6
        viewer.cam.azimuth = 135.0
        viewer.cam.elevation = -12.0
        AlohaMini2ColorDesigner(model, data, viewer, pieces).run()


if __name__ == "__main__":
    launch_alohamini2_color_designer()
