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

"""Run F5 against live AlohaMini1 MuJoCo RGB and the responsive F4 mission manager."""

import argparse
import json
from pathlib import Path
import threading
import time
from typing import Any, cast

import torch

from dimos.core.coordination.module_coordinator import ModuleCoordinator
from dimos.core.global_config import global_config
from dimos.experimental.household_assistant.configuration import PilotConfiguration, load_pilot
from dimos.experimental.household_assistant.contracts import ActionProposal, MissionRequest, Origin
from dimos.experimental.household_assistant.mission_contracts import Arm, MissionSnapshot
from dimos.experimental.household_assistant.mission_module import HouseholdMissionModule
from dimos.experimental.household_assistant.planner import CONFIG_PATH, PlannerSupervisor
from dimos.experimental.household_assistant.planner_backend import LocalVLM
from dimos.experimental.household_assistant.planner_contracts import PlannerConfig, PlannerContext
from dimos.experimental.household_assistant.planner_resources import PlannerResources
from dimos.experimental.household_assistant.spatial_module import HouseholdSpatialModule
from dimos.robot.alohamini1.blueprints.household_mission_sim import household_mission_sim


class RemoteMission:
    """Typed facade: proposals always enter the mission module's atomic RPC gate."""

    def __init__(self, module: HouseholdMissionModule, pilot: PilotConfiguration) -> None:
        self.module = module
        self.pilot = pilot
        self.arm: Arm = "right"
        self.max_age_s = 2.0

    def snapshot(self) -> MissionSnapshot:
        return self.module.get_mission_status()

    def ask(self, reason: str, *, now: float) -> None:
        self.module.ask_mission(reason)

    def admit_planner(
        self,
        *,
        expected: MissionSnapshot,
        request: MissionRequest | None,
        action: ActionProposal | None,
        question: str | None,
        target: str | None,
        now: float,
    ) -> MissionSnapshot:
        return self.module.admit_planner_json(
            expected.model_dump_json(),
            request.model_dump_json() if request else "",
            action.model_dump_json() if action else "",
            question or "",
            target or "",
        )


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.output.mkdir(parents=True, exist_ok=False)
    pilot = load_pilot(CONFIG_PATH.with_name("pilot.json"))
    config = PlannerConfig.model_validate_json(args.config.read_text())
    torch.set_num_threads(2)
    resources = PlannerResources(pilot, args.clip_path, args.yolo_path, args.output / "chroma")
    backend = LocalVLM(config, args.model_path)
    global_config.update(
        **dict(household_mission_sim.global_config_overrides), viewer="none", transport="zenoh"
    )
    coordinator = ModuleCoordinator()
    supervisor: PlannerSupervisor | None = None
    module: HouseholdMissionModule | None = None
    report: dict[str, Any] = {
        "robot": "alohamini1",
        "vlm": config.model_dump(mode="json"),
        "navigation": "live_mujoco",
        "images": "live_front_camera",
        "manipulation": "artificial_F4",
        "act": False,
        "cancel_during_inference": args.cancel_during_inference,
    }
    wait = threading.Event()
    try:
        resources.start()
        backend.start()
        coordinator.start()
        coordinator.load_blueprint(
            household_mission_sim.global_config(n_workers=0),
            {
                "alohamini1simmodule": {"headless": True},
                "voxelgridmapper": {"block_count": 100000},
                "householdmissionmodule": {"automatic_sequence": False},
            },
        )
        module = cast("HouseholdMissionModule", coordinator.get_instance(HouseholdMissionModule))
        spatial = cast("HouseholdSpatialModule", coordinator.get_instance(HouseholdSpatialModule))
        assert module is not None and spatial is not None
        supervisor = PlannerSupervisor(RemoteMission(module, pilot), backend, config)
        deadline = time.monotonic() + args.timeout
        pending_context: PlannerContext | None = None
        cancel_at: float | None = None
        cancellation_request_seeded = False
        while time.monotonic() < deadline:
            bundle = module.get_planning_state()
            if bundle.state.state in {
                "asking",
                "succeeded",
                "failed",
                "cancelled",
                "stop_unconfirmed",
            }:
                break
            if bundle.state.action is not None or bundle.world is None:
                wait.wait(0.1)
                continue
            if args.cancel_during_inference and not cancellation_request_seeded:
                request = MissionRequest(
                    id="f5_cancel_fixture",
                    mission_id="bring_bottle",
                    instruction=args.instruction,
                    object_category="small_bottle",
                    source_id="mesa_sala",
                    destination_id="mesa_dormitorio",
                )
                try:
                    module.submit_request(request.model_dump_json())
                except RuntimeError:
                    wait.wait(0.1)
                    continue
                cancellation_request_seeded = True
                continue
            capture = spatial.get_planner_image()
            if capture is None:
                wait.wait(0.1)
                continue
            image, view = capture
            if pending_context is None:
                observation = resources.perception.observe(image, view, "small_bottle")
                memory = resources.memory.candidates(
                    "small_bottle",
                    map_id=view.map_id,
                    origin=Origin.SIMULATION,
                    clock_id="unix",
                    limit=3,
                )
                context = PlannerContext(
                    instruction=bundle.request.instruction if bundle.request else args.instruction,
                    request=bundle.request,
                    state=bundle.state,
                    world=bundle.world,
                    views=(view,),
                    memory=memory,
                    perception=(observation,),
                    catalog=tuple(s for s in pilot.skills if s.id != "pick_remote_from_floor"),
                    previous_result=bundle.state.reason,
                )
                try:
                    supervisor.begin(context, (image,), now=time.time())
                except ValueError as exc:
                    report["last_wait_reason"] = str(exc)
                    wait.wait(0.1)
                    continue
                resources.memory.remember(image, view)
                pending_context = context
                cancel_at = time.monotonic() + 2 if args.cancel_during_inference else None
            else:
                if cancel_at is not None and time.monotonic() >= cancel_at:
                    requested = time.time()
                    module.cancel_mission()
                    report["cancel_requested_at"] = requested
                    report["cancel_rpc_s"] = time.time() - requested
                    report["planner_result"] = supervisor.cancel_pending(now=time.time())
                    cancel_at = None
                    break
                context = pending_context.model_copy(
                    update={"state": bundle.state, "world": bundle.world, "views": (view,)}
                )
                status = supervisor.poll(context, (image,), now=time.time())
                if status in {"rejected", "discarded"}:
                    # Operator review is deliberate; no automatic retry loop after changed pixels.
                    report["planner_result"] = status
                    module.cancel_mission()
                    break
                if status == "admitted":
                    decision = supervisor.last_decision
                    print(decision.model_dump_json() if decision else status, flush=True)
                    pending_context = None
                    if decision and decision.kind == "ask":
                        break
            wait.wait(0.1)
        else:
            report["session_timeout"] = True
            module.cancel_mission()
    finally:
        if module is not None:
            if module.get_mission_status().state not in {
                "succeeded",
                "asking",
                "failed",
                "cancelled",
            }:
                module.cancel_mission()
            stop_deadline = time.monotonic() + 6
            while (
                module.get_mission_status().state == "stopping" and time.monotonic() < stop_deadline
            ):
                wait.wait(0.1)
            report["final"] = module.get_mission_status().model_dump(mode="json")
            report["events"] = [e.model_dump(mode="json") for e in module.get_mission_events()]
        if supervisor:
            report["planner_records"] = supervisor.records
        backend.close()
        resources.close()
        coordinator.stop()
        (args.output / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--clip-path", required=True, type=Path)
    parser.add_argument("--yolo-path", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument(
        "--instruction", default="Lleva la botella de la sala a la mesa del dormitorio"
    )
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--cancel-during-inference", action="store_true")
    print(json.dumps(run(parser.parse_args()).get("final"), ensure_ascii=False))


if __name__ == "__main__":
    main()
