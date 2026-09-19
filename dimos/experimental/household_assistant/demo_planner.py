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

"""F5 acceptance: real offline VLM + YOLO/CLIP memory + F4 artificial executors.

The recorded RGB replay clock pauses during inference; backend deadlines use wall time.
This is explicitly NOT a live-camera freshness or physical manipulation experiment.
"""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import resource
import threading
import time
from typing import Any

import numpy as np
from PIL import Image as PILImage
import psutil
import torch

from dimos.experimental.household_assistant.configuration import load_pilot
from dimos.experimental.household_assistant.contracts import Evidence, MissionRequest, Origin
from dimos.experimental.household_assistant.mission import MissionManager
from dimos.experimental.household_assistant.mission_sequence import MissionSequence
from dimos.experimental.household_assistant.mission_simulation import (
    ArtificialMissionExecutor,
    simulation_bindings,
)
from dimos.experimental.household_assistant.planner import CONFIG_PATH, PlannerSupervisor
from dimos.experimental.household_assistant.planner_backend import LocalVLM
from dimos.experimental.household_assistant.planner_contracts import PlannerConfig, PlannerContext
from dimos.experimental.household_assistant.planner_resources import PlannerResources
from dimos.experimental.household_assistant.spatial import PoseSample
from dimos.experimental.household_assistant.visual import (
    ObservedView,
    rgb_digest,
)
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class CorpusReplay:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.manifest = json.loads((path / "manifest.json").read_text())
        self.entries = {e["id"]: e for e in self.manifest["cases"]}
        self.sequence = 0

    def capture(self, case: str, now: float) -> tuple[Image, ObservedView]:
        entry = self.entries[case]
        path = (self.path / entry["image"]).resolve()
        if path.parent != self.path or digest(path) != entry["sha256"]:
            raise ValueError("corpus checksum/path mismatch")
        with PILImage.open(path) as source:
            rgb = np.asarray(source.convert("RGB")).copy()
        image = Image(data=rgb, format=ImageFormat.RGB, ts=now, frame_id=entry["frame_id"])
        self.sequence += 1
        view = ObservedView(
            id=f"rgb_{self.sequence}",
            evidence=Evidence(
                origin=Origin.SIMULATION,
                source="recorded_mujoco_rgb_replay",
                reference=f"sha256:{entry['sha256']}@original_unix:{entry['captured_at']}",
                captured_at=now,
                clock_id="f5_replay",
                frame_id=image.frame_id,
            ),
            rgb_sha256=rgb_digest(image),
            observer_pose=PoseSample.model_validate({**entry["observer_pose"], "ts": now}),
            pose_source=entry["pose_source"],
            map_id="household_f5",
            place_id=entry["place_id"],
        )
        return image, view


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.output.mkdir(parents=True, exist_ok=False)
    pilot = load_pilot(CONFIG_PATH.with_name("pilot.json"))
    config = PlannerConfig.model_validate_json(args.config.read_text())
    replay = CorpusReplay(args.corpus)
    torch.set_num_threads(2)
    resources = PlannerResources(pilot, args.clip_path, args.yolo_path, args.output / "chroma")
    wait = threading.Event()
    results: list[dict[str, Any]] = []
    load_started = time.monotonic()
    backend = LocalVLM(config, args.model_path)
    try:
        resources.start()
        memory = resources.memory
        perception = resources.perception
        backend.start()
        load_s = time.monotonic() - load_started
        # Historical retrieval is real CLIP/Chroma, not a fixed text context.
        for i, name in enumerate(("one_bottle", "two_bottles", "empty_table")):
            image, view = replay.capture(name, 10 + i)
            memory.remember(image, view)
        cases = [
            (
                "one_bottle",
                "Lleva la botella de la sala a la mesa del dormitorio",
                "active",
                "observe_at",
            ),
            (
                "two_bottles",
                "Lleva la botella de la sala a la mesa del dormitorio",
                "active",
                "ask",
            ),
            (
                "empty_table",
                "Lleva la botella de la sala a la mesa del dormitorio",
                "active",
                "ask",
            ),
            ("cup_only", "Lleva la botella de la sala a la mesa del dormitorio", "active", "ask"),
            (
                "occluded_bottle",
                "Lleva la botella de la sala a la mesa del dormitorio",
                "active",
                "ask",
            ),
            (
                "bottle_and_cup",
                "Lleva la botella de la sala a la mesa del dormitorio",
                "active",
                "observe_at",
            ),
            (
                "one_bottle_side",
                "Lleva la botella de la sala a la mesa del dormitorio",
                "active",
                "observe_at",
            ),
            (
                "two_bottles_side",
                "Lleva la botella de la sala a la mesa del dormitorio",
                "active",
                "ask",
            ),
            (
                "one_bottle",
                "Por favor, tráeme la botella de la sala al dormitorio",
                "new",
                "request",
            ),
            (
                "one_bottle",
                "¿Puedes dejar la botella de la sala en la mesa de mi habitación?",
                "new",
                "request",
            ),
            ("one_bottle", "Tráeme algo al dormitorio", "new", "ask"),
            ("one_bottle", "Lleva la botella", "new", "ask"),
            ("remote_floor", "Recoge el control remoto del suelo", "new", "ask"),
            ("empty_floor", "Prepárame café en la cocina", "new", "ask"),
            (
                "empty_table",
                "Lleva la botella de la sala a la mesa del dormitorio",
                "held",
                "prepare_transport",
            ),
        ]
        if args.limit:
            cases = cases[: args.limit]
        for index, (name, instruction, stage, expected) in enumerate(cases):
            manager = MissionManager(pilot, simulation_bindings(pilot), clock_id="f5_replay")
            driver = ArtificialMissionExecutor(
                manager, scenario="unknown" if stage != "held" else "nominal"
            )
            driver.place = "mesa_sala"
            now = 100.0
            world = driver.step(now=now)
            request = None
            if stage != "new":
                request = MissionRequest(
                    id=f"case_{index}",
                    mission_id="bring_bottle",
                    instruction=instruction,
                    object_category="small_bottle",
                    source_id="mesa_sala",
                    destination_id="mesa_dormitorio",
                )
                manager.submit(request, now=now)
            if stage == "held":
                assert request is not None
                # F4 baseline creates ONLY the pre-test payload state; it does not choose the tested decision.
                sequence = MissionSequence(manager, request)
                for _ in range(100):
                    now = round(now + 0.1, 6)
                    world = driver.step(now=now)
                    if manager.snapshot().held_object_id:
                        break
                    sequence.advance(world, now=now)
                if manager.snapshot().held_object_id != "bottle_01":
                    raise RuntimeError("held-object setup did not verify grasp")
            image, view = replay.capture(name, now)
            started = time.monotonic()
            observation = perception.observe(image, view, "small_bottle")
            hints = memory.candidates(
                "small_bottle",
                map_id=view.map_id,
                origin=Origin.SIMULATION,
                clock_id="f5_replay",
                limit=3,
            )
            perception_s = time.monotonic() - started
            context = PlannerContext(
                instruction=instruction,
                request=request,
                state=manager.snapshot(),
                world=world,
                views=(view,),
                memory=hints,
                perception=(observation,),
                catalog=tuple(s for s in pilot.skills if s.id != "pick_remote_from_floor"),
                previous_result=manager.snapshot().reason,
            )
            supervisor = PlannerSupervisor(manager, backend, config)
            supervisor.begin(context, (image,), now=now)
            status = "pending"
            shared_peak_mib = 0.0
            while status == "pending":
                process = psutil.Process()
                shared_peak_mib = max(
                    shared_peak_mib,
                    sum(
                        p.memory_info().rss
                        for p in [process, *process.children(recursive=True)]
                        if p.is_running()
                    )
                    / 1024**2,
                )
                # Exercise perception and memory while VLM is busy, measuring actual CPU sharing.
                if args.concurrent:
                    perception.observe(image, view, "small_bottle")
                    memory.candidates(
                        "small_bottle",
                        map_id=view.map_id,
                        origin=Origin.SIMULATION,
                        clock_id="f5_replay",
                        limit=3,
                    )
                status = supervisor.poll(context, (image,), now=now)
                if status == "pending":
                    wait.wait(0.1)
            decision = supervisor.last_decision
            actual = (
                decision.skill
                if decision and decision.kind == "action"
                else decision.kind
                if decision
                else status
            )
            item = {
                "case": index,
                "image_case": name,
                "stage": stage,
                "instruction": instruction,
                "expected": expected,
                "actual": actual,
                "correct": actual == expected,
                "perception_and_retrieval_s": perception_s,
                "shared_rss_upper_bound_mib": shared_peak_mib,
                "status": status,
                "records": supervisor.records,
                "manager_events": [e.model_dump(mode="json") for e in manager.events()],
            }
            results.append(item)
            (args.output / f"case_{index:02d}.json").write_text(
                json.dumps(item, indent=2, ensure_ascii=False) + "\n"
            )
            print(
                json.dumps(
                    {k: item[k] for k in ("case", "image_case", "actual", "expected", "correct")}
                ),
                flush=True,
            )
            if status in {"rejected", "discarded"}:
                backend.start()
        report = {
            "config": config.model_dump(mode="json"),
            "load_s": load_s,
            "model_files": {p.name: digest(p) for p in args.model_path.iterdir() if p.is_file()},
            "sources": {p.name: digest(p) for p in Path(__file__).parent.glob("planner*.py")},
            "corpus_manifest_sha256": digest(args.corpus / "manifest.json"),
            "prompt_sha256": digest(CONFIG_PATH.with_name("planner_prompt.txt")),
            "versions": {
                p: importlib.metadata.version(p)
                for p in ("torch", "transformers", "ultralytics", "chromadb")
            },
            "concurrent_perception_retrieval": args.concurrent,
            "act": "not implemented; no ACT resource measurement claimed",
            "correct": sum(r["correct"] for r in results),
            "total": len(results),
            "parent_peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            "results": results,
            "limitations": [
                "synthetic RGB; fixture object bindings and executors",
                "paused replay clock; wall-clock backend deadline remains enforced",
                "no physical manipulation, instance identification or live scene freshness claim",
                "small development corpus plus two held-out views, not a general accuracy estimate",
            ],
        }
        (args.output / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        )
        return report
    finally:
        backend.close()
        resources.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--clip-path", required=True, type=Path)
    parser.add_argument("--yolo-path", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrent", action="store_true")
    report = run(parser.parse_args())
    print(json.dumps({"correct": report["correct"], "total": report["total"]}))


if __name__ == "__main__":
    main()
