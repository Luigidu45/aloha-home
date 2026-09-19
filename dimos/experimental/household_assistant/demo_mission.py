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

"""Record F4 against native DimOS/MuJoCo navigation; manipulation is artificial.

Run with --scenario nominal, absent, grasp_failure, unverified_grasp, timeout,
retention_loss, posture_loss, disconnect, cancel or blocked. No API/model service
is used and no arm/gripper actuator receives a command.
"""

import argparse
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import subprocess
import time
from typing import Any, cast, get_args

from dimos.constants import DIMOS_PROJECT_ROOT, RECORDINGS_DIR
from dimos.core.coordination.module_coordinator import ModuleCoordinator
from dimos.core.global_config import global_config
from dimos.experimental.household_assistant.configuration import load_pilot
from dimos.experimental.household_assistant.contracts import MissionRequest
from dimos.experimental.household_assistant.mission_module import HouseholdMissionModule
from dimos.experimental.household_assistant.mission_simulation import Scenario
from dimos.experimental.household_assistant.spatial import SPATIAL_SIM_CONFIG
from dimos.experimental.household_assistant.spatial_module import HouseholdSpatialModule
from dimos.robot.alohamini1.blueprints.household_mission_sim import household_mission_sim
from dimos.robot.alohamini1.config import ALOHA_MINI1_NAV_MJCF
from dimos.utils.testing.waiting import wait_until


def run_acceptance(directory: Path, scenario: str) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=False)
    global_config.update(
        **dict(household_mission_sim.global_config_overrides), viewer="none", transport="zenoh"
    )
    coordinator = ModuleCoordinator()
    report: dict[str, Any] = {
        "schema_version": 1,
        "scenario": scenario,
        "robot_model": "alohamini1_cad_zero",
        "navigation_origin": "simulation",
        "localization": "mujoco_ground_truth",
        "manipulation_origin": "test",
        "target_binding_origin": "test",
        "arm": "right",
        "object_mesh_transferred": False,
        "physical_validated": False,
        "vlm_used": False,
        "act_policy_used": False,
        "limitations": [
            "F4 fixture supplies object identity, alignment, wrist and load facts; these are not pixel-derived or physical evidence",
            "MuJoCo performs only base navigation; the bottle mesh is not moved by manipulation",
            "F3 visual candidate/memory adapters are tested separately; this nominal fixture does not prove autonomous visual target grounding",
        ],
    }
    passed = False
    try:
        coordinator.start()
        overrides: dict[str, Any] = {
            "alohamini1simmodule": {"headless": True},
            "voxelgridmapper": {"block_count": 100000},
            "householdmissionmodule": {
                "scenario": "nominal" if scenario in {"cancel", "blocked"} else scenario
            },
        }
        if scenario == "blocked":
            overrides["alohamini1simmodule"]["scene_xml"] = (
                ALOHA_MINI1_NAV_MJCF.parent / "household_navigation_blocked.xml"
            )
            overrides["householdspatialmodule"] = {"navigation_timeout_s": 15.0}
        coordinator.load_blueprint(household_mission_sim.global_config(n_workers=0), overrides)
        module = cast("HouseholdMissionModule", coordinator.get_instance(HouseholdMissionModule))
        spatial = cast("HouseholdSpatialModule", coordinator.get_instance(HouseholdSpatialModule))

        def ready() -> bool:
            frame = module.get_world_frame()
            return frame is not None and any(
                o.key.subject_id == "base" and o.key.predicate == "stopped" and o.value is True
                for o in frame.observations
            )

        wait_until(ready, timeout=45, message="no observed initial stop")
        pilot = load_pilot(SPATIAL_SIM_CONFIG.with_name("pilot.json"))
        request = MissionRequest(
            id="f4_mission_a",
            mission_id=pilot.mission.id,
            instruction="Lleva la botella de la sala al dormitorio",
            object_category=pilot.mission.object_category,
            source_id=pilot.mission.source_id,
            destination_id=pilot.mission.destination_id,
        )
        report["request"] = request.model_dump(mode="json")
        module.submit_request(request.model_dump_json())
        if scenario == "cancel":
            initial_positions: list[tuple[float, float]] = []

            def carrying_and_navigating() -> bool:
                status = module.get_mission_status()
                navigation = spatial.get_status()
                if (
                    status.state != "navigating"
                    or status.held_object_id != "bottle_01"
                    or navigation.state != "navigating"
                    or navigation.pose is None
                ):
                    return False
                if not initial_positions:
                    initial_positions.append((navigation.pose.x, navigation.pose.y))
                return (
                    math.hypot(
                        navigation.pose.x - initial_positions[0][0],
                        navigation.pose.y - initial_positions[0][1],
                    )
                    > 0.15
                )

            wait_until(
                carrying_and_navigating,
                timeout=150,
                message="no loaded navigation before cancellation",
            )
            report["cancel_requested_at"] = time.time()
            module.cancel_mission()

        def done() -> bool:
            return module.get_mission_status().state in {
                "succeeded",
                "asking",
                "failed",
                "cancelled",
                "stop_unconfirmed",
            }

        wait_until(done, timeout=210, message="mission did not reach a decision/terminal state")
        status = module.get_mission_status()
        report["final"] = status.model_dump(mode="json")
        report["spatial_final"] = spatial.get_status().model_dump(mode="json")
        report["adapter_error"] = module.get_adapter_error()
        events = module.get_mission_events()
        report["event_count"] = len(events)
        (directory / "events.jsonl").write_text("".join(e.model_dump_json() + "\n" for e in events))
        frame = module.get_world_frame()
        if frame:
            (directory / "final_frame.json").write_text(frame.model_dump_json(indent=2) + "\n")
        expected = (
            "succeeded"
            if scenario == "nominal"
            else "cancelled"
            if scenario == "cancel"
            else "asking"
            if scenario in {"absent", "ambiguous", "unknown", "occupied"}
            else "stop_unconfirmed"
            if scenario in {"disconnect", "stop_unconfirmed"}
            else "failed"
        )
        assert status.state == expected, report
        assert not report["adapter_error"], report
        if scenario == "nominal":
            assert status.verification is not None
            assert {e.origin.value for e in status.verification.evidence} == {"test", "simulation"}
            assert "place_on_table" in status.completed_actions
        if scenario == "cancel":
            assert status.stop_confirmed_at is not None
            report["cancel_latency_s"] = status.stop_confirmed_at - report["cancel_requested_at"]
            assert report["cancel_latency_s"] < 6
            assert "place_on_table" not in status.completed_actions
            stop_pose = spatial.get_status().pose
            assert stop_pose is not None
            deadline = time.monotonic() + 1.0
            drift: list[float] = []

            def remains_stopped() -> bool:
                pose = spatial.get_status().pose
                assert pose is not None
                drift.append(math.hypot(pose.x - stop_pose.x, pose.y - stop_pose.y))
                return time.monotonic() >= deadline

            wait_until(remains_stopped, timeout=2, interval=0.1)
            report["post_cancel_drift_m"] = max(drift)
            assert max(drift) < 0.02
        passed = True
    finally:
        report["passed"] = passed
        report["git_head"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, cwd=DIMOS_PROJECT_ROOT
        ).strip()
        sources = [
            *sorted(Path(__file__).parent.glob("mission*.py")),
            Path(__file__),
            SPATIAL_SIM_CONFIG,
            SPATIAL_SIM_CONFIG.with_name("pilot.json"),
            Path(__file__).with_name("contracts.py"),
            Path(__file__).with_name("assessment.py"),
            Path(__file__).with_name("configuration.py"),
            Path(__file__).with_name("spatial.py"),
            Path(__file__).with_name("spatial_module.py"),
            DIMOS_PROJECT_ROOT / "dimos/robot/alohamini1/blueprints/household_mission_sim.py",
            DIMOS_PROJECT_ROOT / "dimos/robot/alohamini1/assets/robot.xml",
            DIMOS_PROJECT_ROOT / "dimos/robot/alohamini1/assets/manifest.json",
            DIMOS_PROJECT_ROOT / "dimos/robot/alohamini1/config.py",
            DIMOS_PROJECT_ROOT / "dimos/robot/alohamini1/sim_module.py",
            DIMOS_PROJECT_ROOT / "dimos/robot/alohamini1/blueprints/alohamini1_nav_sim.py",
            *sorted((DIMOS_PROJECT_ROOT / "dimos/navigation/replanning_a_star").glob("*.py")),
        ]
        report["source_sha256"] = {
            str(p.relative_to(DIMOS_PROJECT_ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sources
        }
        report["versions"] = {p: version(p) for p in ("mujoco", "pydantic")}
        (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        coordinator.stop()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=RECORDINGS_DIR / "household_f4" / str(time.time_ns())
    )
    parser.add_argument(
        "--scenario", choices=[*get_args(Scenario), "cancel", "blocked"], default="nominal"
    )
    args = parser.parse_args()
    report = run_acceptance(args.output, args.scenario)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "state": report["final"]["state"],
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
