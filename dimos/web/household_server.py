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

"""F6 cockpit routes on DimOS' existing FastAPI server and HTTP image transport."""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from dimos.experimental.household_assistant.web_session import AssistanceSession, WebCommand
from dimos.web.dimos_interface.api.server import FastAPIServer


class HouseholdWebServer(FastAPIServer):
    def __init__(self, session: AssistanceSession, cockpit: Path, *, host: str, port: int) -> None:
        self.session = session
        self.cockpit = cockpit
        if not (cockpit / "index.html").is_file():
            raise ValueError("Build web/cockpit before starting the household server")
        super().__init__(dev_name="Asistencia doméstica", host=host, port=port)

    def setup_routes(self) -> None:
        # Reuse lifecycle/TLS/HTTP from FastAPIServer without legacy open CORS or raw query routes.
        self.app = FastAPI()

        @self.app.get("/api/assistance/state")
        def state(request: Request) -> dict[str, Any]:
            self.session.client(
                request.client.host if request.client else "unknown",
                request.headers.get("user-agent", ""),
            )
            return self.session.state()

        @self.app.post("/api/assistance/command")
        def command(body: WebCommand, request: Request) -> dict[str, Any]:
            if request.headers.get("x-dimos-session") != self.session.id:
                raise HTTPException(403, "Sesión no confirmada. Actualiza la página.")
            try:
                return self.session.command(body)
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(409, str(exc)) from exc

        @self.app.get("/api/assistance/camera")
        def camera() -> Response:
            image, captured = self.session.image()
            if image is None:
                return Response(status_code=204, headers={"Cache-Control": "no-store"})
            return Response(
                image,
                media_type="image/jpeg",
                headers={"Cache-Control": "no-store", "X-Captured-At": str(captured)},
            )

        @self.app.get("/assistance")
        def page() -> FileResponse:
            return FileResponse(self.cockpit / "index.html", headers={"Cache-Control": "no-store"})

        @self.app.get("/")
        def home() -> RedirectResponse:
            return RedirectResponse("/assistance")

        self.app.mount("/assets", StaticFiles(directory=self.cockpit / "assets"), name="assets")
