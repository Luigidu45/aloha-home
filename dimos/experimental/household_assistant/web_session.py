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

"""F6 conversational state and idempotent commands, independent of VLM inference."""

from collections.abc import Callable
import json
from pathlib import Path
import re
import threading
import time
from typing import Annotated, Any, Literal, Protocol
from uuid import uuid4

from pydantic import Field

from dimos.experimental.household_assistant.contracts import Contract, MissionRequest, Predicate
from dimos.experimental.household_assistant.mission_contracts import (
    MissionPlanningState,
    MissionSnapshot,
)

Destination = Literal["mesa_sala", "mesa_dormitorio"]


class WebCommand(Contract):
    id: Annotated[str, Field(min_length=8, max_length=80)]
    session: str
    kind: Literal[
        "draft",
        "confirm",
        "answer",
        "select",
        "pause",
        "cancel",
        "resume",
        "redirect",
        "confirm_redirect",
    ]
    version: int
    instruction: Annotated[str, Field(max_length=1000)] = ""
    destination: Destination = "mesa_dormitorio"
    object_id: Literal["bottle_01", "bottle_02"] | None = None
    revision: int = -1


class MissionWebPort(Protocol):
    def clarify_mission(self, answer: str, expected_revision: int) -> MissionSnapshot: ...
    def get_planning_state(self) -> MissionPlanningState: ...
    def submit_request(self, request_json: str) -> MissionSnapshot: ...
    def choose_target(self, object_id: str, expected_revision: int) -> MissionSnapshot: ...
    def cancel_mission(self, pause: bool = False) -> MissionSnapshot: ...
    def resume_mission(self) -> MissionSnapshot: ...
    def redirect_mission(self, destination_id: str, expected_revision: int) -> MissionSnapshot: ...


class AssistanceSession:
    """One shared operator session; no HTTP or model work inside its command ledger."""

    def __init__(
        self,
        module: MissionWebPort,
        *,
        mode: str,
        log_path: Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.module = module
        self.mode = mode
        self.id = uuid4().hex
        self.lock = threading.RLock()
        self.clock = clock
        self.log_path = log_path
        self.version = 0
        self.generation = 0
        self.enabled = False
        self.busy = False
        self.message = "Escribe tu solicitud y revisa el destino antes de confirmar."
        self.draft: dict[str, Any] | None = None
        self.redirect_to: Destination | None = None
        self.history: list[dict[str, str]] = []
        self._commands: dict[str, tuple[str, dict[str, Any]]] = {}
        self._clients: set[tuple[str, str]] = set()
        self._media: dict[str, Any] = {"image_at": None, "pose": None, "pose_at": None}
        self._jpeg: bytes | None = None

    def record(self, event: str, **data: Any) -> None:
        with self.lock:
            with self.log_path.open("a") as f:
                f.write(
                    json.dumps(
                        {"at": self.clock(), "session": self.id, "event": event, **data},
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    def client(self, address: str, agent: str) -> None:
        with self.lock:
            key = (address, agent)
            if key not in self._clients:
                self._clients.add(key)
                self.record("browser_connected", address=address, user_agent=agent)

    def update_media(self, jpeg: bytes, image_at: float, pose: dict[str, float]) -> None:
        with self.lock:
            self._jpeg = jpeg
            self._media = {"image_at": image_at, "pose": pose, "pose_at": pose["ts"]}

    def image(self) -> tuple[bytes | None, float | None]:
        with self.lock:
            return self._jpeg, self._media["image_at"]

    def state(self) -> dict[str, Any]:
        bundle = self.module.get_planning_state()
        now = self.clock()
        world = bundle.world
        candidates = []
        if world and 0 <= now - world.captured_at <= 2 and bundle.state.state == "asking":
            for obj in ("bottle_01", "bottle_02"):
                if all(
                    any(
                        o.key.subject_id == obj
                        and o.key.predicate == pred
                        and o.value is True
                        and (pred != Predicate.AT or o.key.place_id == "mesa_sala")
                        and any(0 <= now - e.captured_at <= 2 for e in o.evidence)
                        for o in world.observations
                    )
                    for pred in (Predicate.VISIBLE, Predicate.AT)
                ):
                    candidates.append(
                        {"id": obj, "label": "Botella 1" if obj.endswith("01") else "Botella 2"}
                    )
        with self.lock:
            return {
                "session": self.id,
                "version": self.version,
                "server_at": now,
                "mode": self.mode,
                "mission": bundle.state.model_dump(mode="json"),
                "request": bundle.request.model_dump(mode="json") if bundle.request else None,
                "world_fresh": bool(
                    world and world.connected and 0 <= now - world.captured_at <= 2
                ),
                "busy": self.busy,
                "message": self.message,
                "draft": self.draft,
                "redirect_to": self.redirect_to,
                "candidates": candidates,
                "history": self.history[-20:],
                **self._media,
            }

    def command(self, command: WebCommand) -> dict[str, Any]:
        with self.lock:
            if command.session != self.id:
                raise ValueError("La sesión cambió. Actualiza antes de enviar una nueva orden.")
            payload = command.model_dump_json()
            previous = self._commands.get(command.id)
            if previous:
                if previous[0] != payload:
                    raise ValueError("Identificador reutilizado con otra orden.")
                return previous[1]
            if len(self._commands) >= 2000:
                raise RuntimeError(
                    "Se alcanzó el límite de esta sesión; reinicia con el robot detenido."
                )
            # Pause/cancel remain available even if another client changed the form.
            if command.kind not in {"pause", "cancel"} and command.version != self.version:
                raise ValueError("La conversación cambió. Revisa el estado actualizado.")
            self._apply(command)
            self.version += 1
            response = {"accepted": True, "id": command.id, "version": self.version}
            self._commands[command.id] = (payload, response)
            self.record("command", command=command.model_dump(mode="json"), response=response)
            return response

    def _apply(self, c: WebCommand) -> None:
        bundle = self.module.get_planning_state()
        state = bundle.state
        if c.kind == "answer" and state.state == "asking":
            self.module.clarify_mission(c.instruction, c.revision)
            self.history.append({"role": "user", "text": c.instruction})
            self.generation += 1
            self.enabled = True
            self.message = "Aclaración recibida. Se comprobará con observaciones actuales."
            return
        if c.kind in {"pause", "cancel"}:
            self.generation += 1
            self.enabled = False
            self.draft = None
            self.redirect_to = None
            self.module.cancel_mission(pause=c.kind == "pause")
            self.message = (
                "Parada solicitada. Esperando confirmación del robot."
                if state.request_id
                else "Solicitud retirada."
            )
            return
        if c.kind in {"draft", "answer"}:
            if state.state not in {"idle", "cancelled", "failed", "succeeded"}:
                raise ValueError(
                    "Pausa la misión para cambiar el destino; elige un objeto para resolver la consulta."
                )
            text = c.instruction.strip()
            if not text:
                raise ValueError("Escribe o corrige la solicitud.")
            self.history.append({"role": "user", "text": text})
            self.draft = {"instruction": text, "destination": c.destination, "ready": False}
            words = set(re.findall(r"\w+", text.casefold()))
            if not words.intersection({"botella", "botellita"}):
                self.message = "Esta prueba permite llevar una botella pequeña desde la sala. ¿Quieres pedir esa tarea? Corrige la solicitud para confirmarla."
            else:
                self.draft["ready"] = True
                self.message = "Revisa la tarea: recoger la botella pequeña de la sala y dejarla en la mesa elegida. Confirmar inicia la misión."
            self.history.append({"role": "assistant", "text": self.message})
        elif c.kind == "confirm":
            if not self.draft or not self.draft["ready"]:
                raise ValueError("Primero revisa una solicitud de botella válida.")
            request = MissionRequest(
                id="web_" + c.id.replace("-", "_"),
                mission_id="bring_bottle",
                instruction=self.draft["instruction"],
                object_category="small_bottle",
                source_id="mesa_sala",
                destination_id=self.draft["destination"],
            )
            self.module.submit_request(request.model_dump_json())
            self.generation += 1
            self.enabled = True
            self.draft = None
            self.message = "Solicitud confirmada. Preparando la siguiente etapa."
        elif c.kind == "select":
            if c.object_id is None or state.state != "asking":
                raise ValueError("No hay una elección de objeto pendiente.")
            self.module.choose_target(c.object_id, c.revision)
            self.generation += 1
            self.enabled = True
            self.message = "Objeto elegido. Se comprobará la escena antes de continuar."
            self.history.append({"role": "user", "text": "Elegí " + c.object_id})
        elif c.kind == "resume":
            self.module.resume_mission()
            self.generation += 1
            self.enabled = True
            self.message = "Reanudando desde el estado observado."
        elif c.kind == "redirect":
            if state.state in {"idle", "cancelled", "succeeded", "failed"}:
                raise ValueError("No hay misión activa para cambiar el destino.")
            self.module.cancel_mission(pause=True)
            self.generation += 1
            self.enabled = False
            self.redirect_to = c.destination
            self.message = "Esperando la parada para confirmar el nuevo destino."
        elif c.kind == "confirm_redirect":
            if self.redirect_to is None:
                raise ValueError("Primero elige el nuevo destino.")
            self.module.redirect_mission(self.redirect_to, c.revision)
            self.generation += 1
            self.enabled = True
            self.redirect_to = None
            self.message = "Destino actualizado y carga comprobada. Preparando la continuación."

    def planner_message(self, message: str, *, generation: int) -> None:
        with self.lock:
            if generation == self.generation:
                self.message = message
                self.history.append({"role": "assistant", "text": message})
                self.version += 1
                self.record("planner_message", message=message)
