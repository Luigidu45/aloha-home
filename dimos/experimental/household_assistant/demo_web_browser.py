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

"""Record F6 in a real browser against an idle, explicitly labelled fixture server.

Requires the optional Playwright test tool and its Chromium installation. A mobile
viewport is not a physical phone; the latter remains a separate acceptance step.
"""

import argparse
import json
import math
from pathlib import Path
import time

from playwright.sync_api import sync_playwright


def run(url: str, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    base = url.rstrip("/")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 412, "height": 915},
            record_video_dir=str(output),
            record_video_size={"width": 412, "height": 915},
        )
        try:
            page = context.new_page()
            state = page.request.get(base + "/api/assistance/state").json()
            if state["mode"] != "fixture" or state["mission"]["state"] not in {
                "idle",
                "succeeded",
                "cancelled",
                "failed",
            }:
                raise RuntimeError(
                    "This recording requires a fixture server with no active mission"
                )
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/assistance")
            page.get_by_text("Conectado", exact=True).wait_for()
            page.get_by_label("Tu solicitud").fill("Tráeme algo")
            page.get_by_role("button", name="Revisar solicitud", exact=True).click()
            page.get_by_text("Esta prueba permite", exact=False).first.wait_for()
            assert page.get_by_role("button", name="Confirmar e iniciar").count() == 0
            page.get_by_label("Tu solicitud").fill(
                "Lleva la botella pequeña de la sala al dormitorio"
            )
            page.get_by_role("button", name="Revisar solicitud", exact=True).click()
            page.get_by_role("button", name="Confirmar e iniciar", exact=True).click()
            page.get_by_role("button", name="Elegir Botella 2", exact=True).wait_for(timeout=150000)
            page.screenshot(path=str(output / "choice.png"), full_page=True)
            page.get_by_role("button", name="Elegir Botella 2", exact=True).click()
            page.get_by_text("Objeto confirmado en la pinza (simulación).", exact=True).wait_for(
                timeout=60000
            )
            pickup = page.request.get(base + "/api/assistance/state").json()["pose"]
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                en_route = page.request.get(base + "/api/assistance/state").json()
                pose = en_route["pose"]
                distance = math.hypot(pose["x"] - pickup["x"], pose["y"] - pickup["y"])
                if en_route["mission"]["state"] == "navigating" and distance > 0.35:
                    break
                page.wait_for_timeout(100)
            else:
                raise RuntimeError("Robot never left pickup station with the bottle")
            page.get_by_role("button", name="Pausar", exact=True).click()
            page.get_by_test_id("mission-state").filter(has_text="En pausa").wait_for(timeout=10000)
            page.get_by_label("Lugar de entrega").select_option("mesa_sala")
            page.get_by_role("button", name="Pausar y cambiar destino", exact=True).click()
            page.get_by_role(
                "button", name="Confirmar nuevo destino y continuar", exact=True
            ).click()
            page.get_by_test_id("mission-state").filter(has_text="Entrega verificada").wait_for(
                timeout=150000
            )
            before = page.request.get(base + "/api/assistance/state").json()
            page.reload()
            page.get_by_test_id("mission-state").filter(has_text="Entrega verificada").wait_for()
            context.set_offline(True)
            page.get_by_text("Conexión perdida.", exact=False).wait_for(timeout=10000)
            page.screenshot(path=str(output / "offline.png"), full_page=True)
            context.set_offline(False)
            page.get_by_text("Conectado", exact=True).wait_for(timeout=10000)
            after = page.request.get(base + "/api/assistance/state").json()
            assert before["mission"] == after["mission"]
            assert not errors, errors
            (output / "report.json").write_text(
                json.dumps(
                    {
                        "result": "passed",
                        "browser": "Chromium desktop with mobile viewport; not physical Android",
                        "url": base,
                        "mission": after["mission"],
                        "request": after["request"],
                        "page_errors": errors,
                        "pause_distance_from_pickup_m": distance,
                        "state_before_pause": en_route,
                    },
                    indent=2,
                )
                + "\n"
            )
        finally:
            context.close()
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    run(args.url, args.output)


if __name__ == "__main__":
    main()
