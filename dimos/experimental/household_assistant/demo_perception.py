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

"""Evaluate local F3 perception and DimOS spatial retrieval on recorded pixels."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import resource
import time
from typing import Any

import chromadb
from chromadb.config import Settings
import numpy as np
from PIL import Image as PILImage
import torch

from dimos.experimental.household_assistant.configuration import load_pilot
from dimos.experimental.household_assistant.contracts import Evidence, Origin
from dimos.experimental.household_assistant.local_models import ClipEmbeddingAdapter
from dimos.experimental.household_assistant.perception_bridge import view_from_snapshot
from dimos.experimental.household_assistant.replay_spatial import load_snapshots
from dimos.experimental.household_assistant.semantic_memory import HouseholdMemory, load_catalog
from dimos.experimental.household_assistant.spatial import PoseSample
from dimos.experimental.household_assistant.visual import (
    AbsenceReview,
    HouseholdPerception,
    ObservedView,
    rgb_digest,
)
from dimos.models.embedding.clip import CLIPModel
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat
from dimos.perception.detection.detectors.yolo import Yolo2DDetector
from dimos.perception.spatial_vector_db import SpatialVectorDB
from dimos.perception.visual_memory import VisualMemory


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def box_iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1])
    )
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap
    return overlap / union if union > 0 else 0.0


def detection_metrics(
    predictions: list[tuple[float, ...]], targets: list[tuple[float, ...]]
) -> dict[str, int]:
    remaining = list(targets)
    tp = 0
    for prediction in predictions:
        best = max(
            range(len(remaining)), key=lambda i: box_iou(prediction, remaining[i]), default=None
        )
        if best is not None and box_iou(prediction, remaining[best]) >= 0.5:
            tp += 1
            remaining.pop(best)
    return {
        "true_positive": tp,
        "false_positive": len(predictions) - tp,
        "false_negative": len(remaining),
    }


def evaluate(
    corpus: Path,
    output: Path,
    *,
    clip_path: Path,
    yolo_path: Path,
    device: str,
    f2_recording: Path | None = None,
    reviews: Path | None = None,
) -> dict[str, Any]:
    if not yolo_path.is_file() or not (clip_path / "model.safetensors").is_file():
        raise ValueError("prepare local weights first; this runner never downloads weights")
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(4)
    clip_hash = file_hash(clip_path / "model.safetensors")
    yolo_hash = file_hash(yolo_path)
    model_id = f"dimos_yolo:{yolo_hash}:device={device}:conf=0.5:tracking=false"
    embedding_files = {
        p.name: file_hash(p)
        for p in sorted(clip_path.iterdir())
        if p.is_file() and p.suffix in {".json", ".txt", ".safetensors"}
    }
    embedding_fingerprint = hashlib.sha256(
        json.dumps(embedding_files, sort_keys=True).encode()
    ).hexdigest()
    embedding_id = f"dimos_clip:{embedding_fingerprint}"
    manifest = json.loads((corpus / "manifest.json").read_text())
    catalog = load_catalog(load_pilot(Path(__file__).parent / "configs" / "pilot.json"))
    clip = CLIPModel(model_name=str(clip_path.resolve()), device=device)
    detector = Yolo2DDetector(
        model_path=str(yolo_path.resolve().parent),
        model_name=yolo_path.name,
        device=device,
        tracking=False,
    )
    perception = HouseholdPerception(detector, model_id)
    embedding = ClipEmbeddingAdapter(clip)
    client = chromadb.PersistentClient(
        path=str(output / "chroma"), settings=Settings(anonymized_telemetry=False)
    )
    store = SpatialVectorDB(
        collection_name="household_f3",
        chroma_client=client,
        visual_memory=VisualMemory(),
        embedding_provider=embedding,
    )
    memory = HouseholdMemory(store, embedding, catalog, embedding_id=embedding_id)
    cases = []
    views = {}
    started = time.perf_counter()
    try:
        for entry in manifest["cases"]:
            path = (corpus / entry["image"]).resolve()
            if path.parent != corpus.resolve() or file_hash(path) != entry["sha256"]:
                raise ValueError("invalid corpus image reference or checksum")
            image = Image(
                data=np.asarray(PILImage.open(path).convert("RGB")),
                format=ImageFormat.RGB,
                ts=entry["captured_at"],
                frame_id=entry["frame_id"],
            )
            view = ObservedView(
                id=entry["id"],
                evidence=Evidence(
                    origin=entry["origin"],
                    source="mujoco_rgb_render",
                    reference=str(path),
                    captured_at=image.ts,
                    clock_id=entry["clock_id"],
                    frame_id=image.frame_id,
                ),
                rgb_sha256=rgb_digest(image),
                observer_pose=PoseSample.model_validate(entry["observer_pose"]),
                pose_source=entry["pose_source"],
                map_id="household_f3",
                place_id=entry["place_id"],
            )
            views[view.id] = view
            t0 = time.perf_counter()
            # Only pixels, provenance and requested category cross the inference boundary.
            category = catalog.target(
                "control" if entry["place_id"] == "suelo_sala" else "botella"
            ).category
            observation = perception.observe(image, view, category)
            inference_s = time.perf_counter() - t0
            memory.remember(image, view)
            memory.record_observation(observation)
            # Ground truth is consumed only AFTER inference, exclusively for scoring.
            annotation = entry["annotation"]
            metrics = detection_metrics(
                [c.bbox_xyxy for c in observation.candidates],
                [tuple(b) for b in annotation["visible_boxes"]],
            )
            cases.append(
                {
                    "id": view.id,
                    "split": annotation["split"],
                    "category": category,
                    "annotation": annotation,
                    "result": observation.model_dump(mode="json"),
                    "inference_s": inference_s,
                    "metrics_iou_0_5": metrics,
                }
            )
        retrieval_before = memory.candidates(
            "small_bottle",
            map_id="household_f3",
            origin=Origin.SIMULATION,
            clock_id="unix",
            limit=10,
        )
        applied_reviews = []
        if reviews is not None:
            for entry in json.loads(reviews.read_text()):
                view = views[entry["view_id"]]
                if view.rgb_sha256 != entry["rgb_sha256"]:
                    raise ValueError("review refers to different pixels")
                review = AbsenceReview(
                    view=view,
                    category=entry["category"],
                    reviewer=entry["reviewer"],
                    region_fully_visible=entry["region_fully_visible"],
                    target_absent=entry["target_absent"],
                    reviewed_at=entry["reviewed_at"],
                    note=entry["note"],
                )
                memory.record_absence(review)
                applied_reviews.append(review.model_dump(mode="json"))
        retrieval_after = memory.candidates(
            "small_bottle",
            map_id="household_f3",
            origin=Origin.SIMULATION,
            clock_id="unix",
            limit=10,
        )
        f2_results = []
        if f2_recording is not None:
            for i, snapshot in enumerate(load_snapshots(f2_recording)):
                view = view_from_snapshot(
                    snapshot, view_id=f"f2_view_{i}", map_id="household_f2", retain_place=False
                )
                # Deliberately do not look up a station pose: use the recorded localization.
                memory.remember(snapshot.image, view)
                observation = perception.observe(snapshot.image, view, "small_bottle")
                f2_results.append(observation.model_dump(mode="json"))
        f2_retrieval = memory.candidates(
            "small_bottle", map_id="household_f2", origin=Origin.SIMULATION, clock_id="unix"
        )
        totals = {
            key: sum(c["metrics_iou_0_5"][key] for c in cases)
            for key in ("true_positive", "false_positive", "false_negative")
        }
        report = {
            "schema_version": 1,
            "origin": "simulation",
            "implementation_revision": "working_tree_f3",
            "device": device,
            "detector": model_id,
            "embedding": embedding_id,
            "embedding_files": embedding_files,
            "clip_weights_sha256": clip_hash,
            "corpus_manifest_sha256": file_hash(corpus / "manifest.json"),
            "versions": {
                p: importlib.metadata.version(p)
                for p in ("torch", "transformers", "ultralytics", "chromadb", "mujoco")
            },
            "cases": cases,
            "totals_iou_0_5": totals,
            "retrieval_before_reviews": [c.model_dump(mode="json") for c in retrieval_before],
            "retrieval_after_reviews": [c.model_dump(mode="json") for c in retrieval_after],
            "absence_reviews": applied_reviews,
            "f2_perception_unannotated": f2_results,
            "f2_retrieval_without_registered_place": [
                c.model_dump(mode="json") for c in f2_retrieval
            ],
            "elapsed_s": time.perf_counter() - started,
            "peak_process_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
            "limitations": [
                "synthetic fixtures, small corpus, not a physical accuracy estimate",
                "observer pose is not object pose",
                "detector score and CLIP distance are not calibrated probabilities",
                "negative review is explicit human/visual review, not YOLO absence detection",
                "F2 images unannotated: detections reported without accuracy claim",
            ],
        }
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        (output / "journal.json").write_text(json.dumps(memory.journal(), indent=2) + "\n")
        return report
    finally:
        detector.stop()
        clip.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--clip-path", type=Path, required=True)
    parser.add_argument("--yolo-path", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--f2-recording", type=Path)
    parser.add_argument("--reviews", type=Path)
    args = parser.parse_args()
    report = evaluate(
        args.corpus,
        args.output,
        clip_path=args.clip_path,
        yolo_path=args.yolo_path,
        device=args.device,
        f2_recording=args.f2_recording,
        reviews=args.reviews,
    )
    print(
        json.dumps(
            {
                "totals": report["totals_iou_0_5"],
                "elapsed_s": report["elapsed_s"],
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
