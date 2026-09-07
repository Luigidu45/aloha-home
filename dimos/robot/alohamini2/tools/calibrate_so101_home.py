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

"""Interactive dual-SO101 home-pose editor for AlohaMini2."""

from __future__ import annotations

from functools import partial
import math
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

import mujoco
import mujoco.viewer

from dimos.robot.alohamini2.config import ALOHA_MINI2_NAV_MJCF, ALOHA_MINI2_SO101_HOME
from dimos.robot.alohamini2.so101_home import (
    SO101_JOINT_BODIES,
    SO101_JOINT_RANGES,
    SO101_SIDES,
    default_so101_home_pose,
    load_so101_home_pose,
    save_so101_home_pose,
)

JOINT_LABELS = {
    "shoulder_pan": "Base / hombro horizontal",
    "shoulder_lift": "Hombro vertical",
    "elbow_flex": "Codo",
    "wrist_flex": "Muñeca vertical",
    "wrist_roll": "Giro de muñeca",
    "gripper": "Apertura del gripper",
}


def build_calibration_model() -> mujoco.MjModel:
    """Build an articulated editor model from the optimized navigation MJCF."""
    spec = mujoco.MjSpec.from_file(str(ALOHA_MINI2_NAV_MJCF))
    for side in SO101_SIDES:
        for joint_name, limits in SO101_JOINT_RANGES.items():
            body_part, base_quaternion = SO101_JOINT_BODIES[joint_name]
            body = spec.body(f"cad_{side}_so101_{body_part}_body")
            if body is None:
                raise RuntimeError(f"Missing {side} SO101 body {body_part}")
            body.quat = base_quaternion
            # The navigation model omits inertials because its arms are rigid.
            # Lightweight explicit inertials make only this editor articulatable.
            body.mass = 0.05
            body.inertia = [1e-4, 1e-4, 1e-4]
            body.explicitinertial = True
            joint = body.add_joint(
                name=f"{side}_{joint_name}",
                type=mujoco.mjtJoint.mjJNT_HINGE,
                axis=[0.0, 0.0, 1.0],
            )
            joint.limited = True
            joint.range = limits
    return spec.compile()


class SO101HomeEditor:
    """Tk controls synchronized with a passive MuJoCo viewer."""

    def __init__(self, model: mujoco.MjModel, data: mujoco.MjData, viewer: Any) -> None:
        self._model = model
        self._data = data
        self._viewer = viewer
        self._root = tk.Tk()
        self._root.title("AlohaMini2 — calibrar home de los brazos SO101")
        self._root.protocol("WM_DELETE_WINDOW", self._close)
        self._linked = tk.BooleanVar(value=True)
        self._status = tk.StringVar(value=f"Postura cargada desde {ALOHA_MINI2_SO101_HOME}")
        self._variables: dict[tuple[str, str], tk.DoubleVar] = {}
        self._qpos_addresses = self._joint_qpos_addresses()
        self._build_controls()
        self._set_pose(load_so101_home_pose(ALOHA_MINI2_SO101_HOME))
        self._root.after(16, self._refresh_viewer)

    def _joint_qpos_addresses(self) -> dict[tuple[str, str], int]:
        addresses: dict[tuple[str, str], int] = {}
        for side in SO101_SIDES:
            for joint_name in SO101_JOINT_RANGES:
                full_name = f"{side}_{joint_name}"
                joint_id = mujoco.mj_name2id(self._model, mujoco.mjtObj.mjOBJ_JOINT, full_name)
                if joint_id < 0:
                    raise RuntimeError(f"Calibration joint {full_name} was not created")
                addresses[(side, joint_name)] = int(self._model.jnt_qposadr[joint_id])
        return addresses

    def _build_controls(self) -> None:
        instructions = ttk.Label(
            self._root,
            text=(
                "Mueve cada deslizador y observa el robot en MuJoCo. Los valores se "
                "muestran en grados; el archivo se guarda en radianes."
            ),
            wraplength=920,
        )
        instructions.grid(row=0, column=0, columnspan=2, padx=12, pady=(12, 6), sticky="w")

        for column, side in enumerate(SO101_SIDES):
            title = "Brazo izquierdo" if side == "left" else "Brazo derecho"
            frame = ttk.LabelFrame(self._root, text=title)
            frame.grid(row=1, column=column, padx=10, pady=6, sticky="nsew")
            self._root.columnconfigure(column, weight=1)
            for row, (joint_name, limits) in enumerate(SO101_JOINT_RANGES.items()):
                ttk.Label(frame, text=JOINT_LABELS[joint_name]).grid(
                    row=row * 2, column=0, padx=8, pady=(7, 0), sticky="w"
                )
                variable = tk.DoubleVar(value=0.0)
                self._variables[(side, joint_name)] = variable
                scale = tk.Scale(
                    frame,
                    from_=math.degrees(limits[0]),
                    to=math.degrees(limits[1]),
                    resolution=0.25,
                    orient=tk.HORIZONTAL,
                    length=420,
                    variable=variable,
                    command=partial(self._on_slider, side, joint_name),
                )
                scale.grid(row=row * 2 + 1, column=0, padx=8, pady=(0, 3), sticky="ew")

        actions = ttk.Frame(self._root)
        actions.grid(row=2, column=0, columnspan=2, padx=12, pady=8, sticky="ew")
        ttk.Checkbutton(
            actions,
            text="Mover ambos brazos sincronizados",
            variable=self._linked,
        ).pack(side=tk.LEFT)
        ttk.Button(actions, text="Postura predeterminada", command=self._restore_default).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(actions, text="Recargar guardada", command=self._reload).pack(
            side=tk.RIGHT, padx=4
        )
        ttk.Button(actions, text="GUARDAR HOME", command=self._save).pack(side=tk.RIGHT, padx=4)
        ttk.Label(self._root, textvariable=self._status, wraplength=920).grid(
            row=3, column=0, columnspan=2, padx=12, pady=(0, 12), sticky="w"
        )

    def _on_slider(self, side: str, joint_name: str, degrees_value: str) -> None:
        angle = math.radians(float(degrees_value))
        self._set_joint(side, joint_name, angle)
        if self._linked.get():
            other_side = "right" if side == "left" else "left"
            self._variables[(other_side, joint_name)].set(float(degrees_value))
            self._set_joint(other_side, joint_name, angle)
        self._status.set("Postura modificada; pulsa GUARDAR HOME para conservarla.")

    def _set_joint(self, side: str, joint_name: str, angle: float) -> None:
        with self._viewer.lock():
            self._data.qpos[self._qpos_addresses[(side, joint_name)]] = angle
            mujoco.mj_forward(self._model, self._data)

    def _current_pose(self) -> dict[str, dict[str, float]]:
        return {
            side: {
                joint_name: float(self._data.qpos[self._qpos_addresses[(side, joint_name)]])
                for joint_name in SO101_JOINT_RANGES
            }
            for side in SO101_SIDES
        }

    def _set_pose(self, pose: dict[str, dict[str, float]]) -> None:
        for side in SO101_SIDES:
            for joint_name, angle in pose[side].items():
                self._variables[(side, joint_name)].set(math.degrees(angle))
                self._set_joint(side, joint_name, angle)

    def _save(self) -> None:
        try:
            save_so101_home_pose(ALOHA_MINI2_SO101_HOME, self._current_pose())
        except (OSError, ValueError) as error:
            self._status.set(f"No se pudo guardar HOME: {error}")
            messagebox.showerror("No se pudo guardar HOME", str(error), parent=self._root)
            return
        self._status.set("HOME guardado. Reinicia alohamini2-nav-sim para aplicar esta postura.")

    def _reload(self) -> None:
        self._set_pose(load_so101_home_pose(ALOHA_MINI2_SO101_HOME))
        self._status.set("Se recargó la última postura guardada.")

    def _restore_default(self) -> None:
        self._set_pose(default_so101_home_pose())
        self._status.set("Se restauró la postura predeterminada; todavía no se guardó.")

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
        """Run the controls until either window is closed."""
        self._root.mainloop()


def launch_so101_home_editor() -> None:
    """Open the dual-arm editor and its MuJoCo preview window."""
    model = build_calibration_model()
    data = mujoco.MjData(model)
    with mujoco.viewer.launch_passive(model, data) as viewer:
        viewer.cam.lookat[:] = (0.0, 0.0, 0.55)
        viewer.cam.distance = 1.55
        viewer.cam.azimuth = 135.0
        viewer.cam.elevation = -12.0
        SO101HomeEditor(model, data, viewer).run()


if __name__ == "__main__":
    launch_so101_home_editor()
