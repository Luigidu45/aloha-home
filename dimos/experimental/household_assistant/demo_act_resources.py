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

"""Measure resident and concurrent ACT/VLM CPU resources without dispatching commands."""

import argparse
import json
from pathlib import Path
import threading
import time

import numpy as np
import psutil

from dimos.experimental.household_assistant.act_contracts import synthetic_observation
from dimos.experimental.household_assistant.act_process import LeRobotProcess
from dimos.experimental.household_assistant.configuration import load_pilot
from dimos.experimental.household_assistant.contracts import MissionRequest
from dimos.experimental.household_assistant.demo_planner import CorpusReplay
from dimos.experimental.household_assistant.mission import MissionManager
from dimos.experimental.household_assistant.mission_simulation import (
    ArtificialMissionExecutor,
    simulation_bindings,
)
from dimos.experimental.household_assistant.planner import CONFIG_PATH, PROMPT_PATH, prompt_for
from dimos.experimental.household_assistant.planner_backend import LocalVLM, pack_image
from dimos.experimental.household_assistant.planner_contracts import PlannerConfig, PlannerContext
from dimos.experimental.household_assistant.planner_options import available_actions
from dimos.experimental.household_assistant.planner_resources import PlannerResources


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--lerobot-source", type=Path, required=True)
    parser.add_argument("--deps", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--vlm-path", type=Path, default=Path(".ignore.f5/models/qwen"))
    parser.add_argument("--clip-path", type=Path, default=Path(".ignore.f3/models/clip"))
    parser.add_argument("--yolo-path", type=Path, default=Path(".ignore.f3/models/yolo/yolo11n.pt"))
    parser.add_argument("--corpus", type=Path, default=Path(".ignore.f5/corpus"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    pilot = load_pilot(CONFIG_PATH.with_name("pilot.json"))
    config = PlannerConfig.model_validate_json(CONFIG_PATH.read_text())
    backend = LocalVLM(config, args.vlm_path)
    resources = PlannerResources(pilot, args.clip_path, args.yolo_path, args.output / "chroma")
    act = LeRobotProcess(
        python=args.python,
        source=args.lerobot_source,
        deps=args.deps,
        profile_path=args.profile,
        checkpoint=args.checkpoint,
        log=args.output / "act_worker.log",
    )
    wait = threading.Event()

    def infer() -> float:
        started = time.monotonic()
        act.predict(synthetic_observation(act.profile, 0, 0, at=time.time()))
        return time.monotonic() - started

    try:
        standalone = [infer() for _ in range(5)]
        resources.start()
        backend.start()
        resident = [infer() for _ in range(5)]
        replay = CorpusReplay(args.corpus)
        image, view = replay.capture("one_bottle", 100)
        manager = MissionManager(pilot, simulation_bindings(pilot), clock_id="f5_replay")
        driver = ArtificialMissionExecutor(manager)
        world = driver.step(now=100)
        request = MissionRequest(
            id="resources_f7",
            mission_id="bring_bottle",
            instruction="Lleva la botella al dormitorio",
            object_category="small_bottle",
            source_id="mesa_sala",
            destination_id="mesa_dormitorio",
        )
        manager.submit(request, now=100)
        perception = resources.perception.observe(image, view, "small_bottle")
        resources.memory.remember(image, view)
        context = PlannerContext(
            instruction=request.instruction,
            request=request,
            state=manager.snapshot(),
            world=world,
            views=(view,),
            memory=(),
            perception=(perception,),
            catalog=tuple(s for s in pilot.skills if s.id != "pick_remote_from_floor"),
            previous_result="resource_test_no_execution",
        )
        options = available_actions(pilot, context, max_age_s=2)
        backend.submit(
            prompt_for(context, PROMPT_PATH.read_text(), options),
            [pack_image(view, image)],
            active_mission=True,
            action_options=[
                {"skill": a.skill_id, "destination": a.destination_id, "object_id": a.object_id}
                for a in options
            ],
        )
        latencies = []
        peak_rss_mib = 0.0
        started = time.monotonic()
        reply = None
        while reply is None:
            latencies.append(infer())
            process = psutil.Process()
            peak_rss_mib = max(
                peak_rss_mib,
                sum(
                    p.memory_info().rss
                    for p in [process, *process.children(recursive=True)]
                    if p.is_running()
                )
                / 1024**2,
            )
            reply = backend.poll()
            if reply is None:
                wait.wait(0.1)
        report = {
            "physical_actuators": False,
            "act_profile": act.profile.fingerprint(),
            "act_architecture": "reduced_CPU_smoke_not_full_production_ACT",
            "standalone_roundtrip_s": standalone,
            "models_resident_roundtrip_s": resident,
            "concurrent_roundtrip_s": latencies,
            "concurrent_p95_s": float(np.percentile(latencies, 95)),
            "concurrent_over_100ms": sum(x > 0.1 for x in latencies),
            "peak_combined_rss_mib": peak_rss_mib,
            "rss_note": "sum of process RSS; shared pages may be counted more than once",
            "elapsed_concurrent_s": time.monotonic() - started,
            "vlm_reply": reply.model_dump(mode="json"),
            "perception_memory": "CLIP/YOLO/Chroma loaded; one observation and remember before concurrent inference",
            "interpretation": "Inference-only contention probe, not a mission or physical control frequency benchmark",
        }
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(
            json.dumps(
                {
                    k: v
                    for k, v in report.items()
                    if k not in {"concurrent_roundtrip_s", "vlm_reply"}
                }
            )
        )
    finally:
        act.close()
        backend.close()
        resources.close()


if __name__ == "__main__":
    main()
