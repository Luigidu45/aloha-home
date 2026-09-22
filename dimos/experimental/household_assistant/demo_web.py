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

"""Serve the F6 cockpit with live AlohaMini1 MuJoCo and either F5 or the labelled F4 fixture."""

import argparse
import json
from pathlib import Path
from typing import cast

from dimos.constants import DIMOS_PROJECT_ROOT
from dimos.core.coordination.module_coordinator import ModuleCoordinator
from dimos.core.global_config import global_config
from dimos.experimental.household_assistant.configuration import load_pilot
from dimos.experimental.household_assistant.mission_module import HouseholdMissionModule
from dimos.experimental.household_assistant.planner import CONFIG_PATH
from dimos.experimental.household_assistant.planner_backend import LocalVLM
from dimos.experimental.household_assistant.planner_contracts import PlannerConfig
from dimos.experimental.household_assistant.planner_resources import PlannerResources
from dimos.experimental.household_assistant.spatial_module import HouseholdSpatialModule
from dimos.experimental.household_assistant.web_runtime import AssistanceRuntime
from dimos.experimental.household_assistant.web_session import AssistanceSession
from dimos.robot.alohamini1.blueprints.household_mission_sim import household_mission_sim
from dimos.web.household_server import HouseholdWebServer


def run(args: argparse.Namespace) -> None:
    args.output.mkdir(parents=True, exist_ok=False)
    pilot = load_pilot(CONFIG_PATH.with_name("pilot.json"))
    config = PlannerConfig.model_validate_json(args.config.read_text())
    global_config.update(
        **dict(household_mission_sim.global_config_overrides), viewer="none", transport="zenoh"
    )
    coordinator = ModuleCoordinator()
    runtime: AssistanceRuntime | None = None
    server: HouseholdWebServer | None = None
    module: HouseholdMissionModule | None = None
    session: AssistanceSession | None = None
    try:
        coordinator.start()
        coordinator.load_blueprint(
            household_mission_sim.global_config(n_workers=0),
            {
                "alohamini1simmodule": {"headless": True},
                "voxelgridmapper": {"block_count": 100000},
                "householdmissionmodule": {
                    "automatic_sequence": args.fixture,
                    "scenario": args.scenario,
                },
            },
        )
        module = cast("HouseholdMissionModule", coordinator.get_instance(HouseholdMissionModule))
        spatial = cast("HouseholdSpatialModule", coordinator.get_instance(HouseholdSpatialModule))
        session = AssistanceSession(
            module,
            mode="fixture" if args.fixture else "vlm",
            log_path=args.output / "interaction.jsonl",
        )
        backend = None if args.fixture else LocalVLM(config, args.model_path)
        resources = (
            None
            if args.fixture
            else PlannerResources(pilot, args.clip_path, args.yolo_path, args.output / "chroma")
        )
        runtime = AssistanceRuntime(session, module, spatial, pilot, config, backend, resources)
        server = HouseholdWebServer(session, args.cockpit, host=args.host, port=args.port)
        runtime.start()
        print(
            json.dumps(
                {
                    "event": "ready",
                    "host": args.host,
                    "port": args.port,
                    "path": "/assistance",
                    "mode": session.mode,
                }
            ),
            flush=True,
        )
        server.run(ssl=args.tls_certs is not None, ssl_certs_dir=args.tls_certs)
    finally:
        if server:
            server.shutdown()
            server.dispose_all()
        try:
            if runtime:
                runtime.stop()
            if module:
                (args.output / "mission_events.json").write_text(
                    json.dumps(
                        [e.model_dump(mode="json") for e in module.get_mission_events()], indent=2
                    )
                    + "\n"
                )
            if session:
                (args.output / "final.json").write_text(
                    json.dumps(session.state(), indent=2) + "\n"
                )
        finally:
            coordinator.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--host", default=global_config.listen_host)
    parser.add_argument("--port", type=int, default=global_config.household_web_port)
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="Use labelled F4 scripted decisions for interaction tests, not a VLM",
    )
    parser.add_argument("--scenario", choices=["nominal", "ambiguous", "absent"], default="nominal")
    parser.add_argument("--model-path", type=Path, default=Path(".ignore.f5/models/qwen"))
    parser.add_argument("--clip-path", type=Path, default=Path(".ignore.f3/models/clip"))
    parser.add_argument("--yolo-path", type=Path, default=Path(".ignore.f3/models/yolo/yolo11n.pt"))
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--cockpit", type=Path, default=DIMOS_PROJECT_ROOT / "web/cockpit/dist")
    parser.add_argument(
        "--tls-certs",
        type=Path,
        help="Existing DimOS TLS certificate directory; Android must trust its certificate",
    )
    run(parser.parse_args())


if __name__ == "__main__":
    main()
