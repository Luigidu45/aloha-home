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

"""Reproducible F4 fault traces with a controlled clock and artificial executors."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, cast

from dimos.constants import RECORDINGS_DIR
from dimos.experimental.household_assistant.configuration import load_pilot
from dimos.experimental.household_assistant.contracts import MissionRequest
from dimos.experimental.household_assistant.mission import MissionManager
from dimos.experimental.household_assistant.mission_sequence import MissionSequence
from dimos.experimental.household_assistant.mission_simulation import (
    ArtificialMissionExecutor,
    Scenario,
    simulation_bindings,
)
from dimos.experimental.household_assistant.spatial import SPATIAL_SIM_CONFIG

CASES = {
    "nominal": "succeeded",
    "absent": "asking",
    "ambiguous": "asking",
    "unknown": "asking",
    "grasp_failure": "failed",
    "unverified_grasp": "failed",
    "timeout": "failed",
    "retention_loss": "failed",
    "posture_loss": "failed",
    "occupied": "asking",
    "disconnect": "stop_unconfirmed",
    "stop_unconfirmed": "stop_unconfirmed",
    "cancel": "cancelled",
    "pause_resume": "succeeded",
}


def run_cases(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    pilot = load_pilot(SPATIAL_SIM_CONFIG.with_name("pilot.json"))
    reports = []
    for name, expected in CASES.items():
        manager = MissionManager(
            pilot,
            simulation_bindings(pilot),
            clock_id="f4_test_clock",
            stop_timeout_s=1,
            verification_timeout_s=0.5,
        )
        executor = ArtificialMissionExecutor(
            manager,
            scenario=cast("Scenario", "nominal" if name in {"cancel", "pause_resume"} else name),
        )
        request = MissionRequest(
            id=f"f4_{name}",
            mission_id=pilot.mission.id,
            instruction="Traer botella al dormitorio",
            object_category=pilot.mission.object_category,
            source_id=pilot.mission.source_id,
            destination_id=pilot.mission.destination_id,
        )
        executor.step(now=100)
        manager.submit(request, now=100)
        sequence = MissionSequence(manager, request)
        intervened = False
        for i in range(1, 2000):
            now = 100 + i * 0.1
            frame = executor.step(now=now)
            status = manager.snapshot()
            if (
                name in {"cancel", "pause_resume"}
                and not intervened
                and status.state == "navigating"
                and status.held_object_id
            ):
                manager.cancel(now=now, pause=name == "pause_resume")
                intervened = True
            elif name == "pause_resume" and status.state == "paused":
                manager.resume(now=now)
            sequence.advance(frame, now=now)
            if manager.snapshot().state in {
                "succeeded",
                "asking",
                "failed",
                "cancelled",
                "stop_unconfirmed",
            }:
                break
        status = manager.snapshot()
        events = manager.events()
        (output / f"{name}.jsonl").write_text("".join(e.model_dump_json() + "\n" for e in events))
        assert status.state == expected, (name, status)
        assert (executor.placed is not None) == (expected == "succeeded"), (name, status)
        assert len({c.action.id for c in executor.dispatched}) == len(executor.dispatched)
        reports.append(
            {
                "case": name,
                "expected": expected,
                "state": status.state,
                "reason": status.reason,
                "event_count": len(events),
                "dispatched_skills": [c.action.skill_id for c in executor.dispatched],
                "final": status.model_dump(mode="json"),
                "trace_sha256": hashlib.sha256((output / f"{name}.jsonl").read_bytes()).hexdigest(),
            }
        )
    report = {
        "schema_version": 1,
        "origin": "test",
        "clock_id": "f4_test_clock",
        "arm": "right",
        "passed": True,
        "cases": reports,
        "physical_validated": False,
        "pixel_perception_validated": False,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=RECORDINGS_DIR / "household_f4_cases")
    args = parser.parse_args()
    result = run_cases(args.output)
    print(
        json.dumps(
            {"passed": result["passed"], "cases": len(result["cases"]), "output": str(args.output)}
        )
    )


if __name__ == "__main__":
    main()
