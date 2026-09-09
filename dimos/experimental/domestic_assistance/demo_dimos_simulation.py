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

"""Run one Phase-2 nominal episode through the DimOS MuJoCo blueprint."""

import argparse
import json
import time

from dimos.core.global_config import global_config
from dimos.porcelain.dimos import Dimos

BLUEPRINTS = {
    "recoger_ropa": "alohamini2-domestic-clothes-sim",
    "preparar_bandeja": "alohamini2-domestic-tray-sim",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id", choices=tuple(BLUEPRINTS))
    parser.add_argument("episode_id")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--transport", choices=("lcm", "zenoh"), default="zenoh")
    parser.add_argument(
        "--connect",
        action="store_true",
        help="Attach to an already running matching blueprint instead of starting it.",
    )
    args = parser.parse_args()

    if args.connect:
        global_config.update(transport=args.transport)
        app = Dimos.connect(timeout=10.0)
    else:
        app = Dimos(
            transport=args.transport,
            simulation="mujoco",
            viewer="none",
        )
    try:
        if not args.connect:
            app.run(BLUEPRINTS[args.task_id])
        module = app.get_module("domesticassistancesimulationmodule")
        sensor_deadline = time.monotonic() + 30.0
        status = None
        while time.monotonic() < sensor_deadline:
            try:
                status = module.episode_status()
            except Exception:
                time.sleep(0.25)
                continue
            if status["sensors_ready"]:
                break
            time.sleep(0.25)
        if status is None or not status["sensors_ready"]:
            raise RuntimeError(f"simulation sensors did not become ready: {status}")

        journal = module.start_nominal_episode(args.episode_id, 0)
        print(f"journal={journal}")
        episode_deadline = time.monotonic() + args.timeout
        while time.monotonic() < episode_deadline:
            time.sleep(0.5)
            try:
                status = module.episode_status()
            except Exception:
                # Planning is currently a synchronous DimOS RPC and can briefly delay
                # status calls while A* computes. The episode itself remains bounded by
                # MissionRunner and the outer deadline below.
                continue
            if not status["active"]:
                print(json.dumps(status, indent=2, sort_keys=True))
                return 0 if status["summary"] is not None and status["error"] is None else 1
        module.cancel_episode()
        raise TimeoutError(f"episode exceeded {args.timeout} seconds")
    finally:
        app.stop()


if __name__ == "__main__":
    raise SystemExit(main())
