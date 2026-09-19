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

"""Owned local F3 perception and persistent retrieval resources for F5 sessions."""

import hashlib
from pathlib import Path

import chromadb
from chromadb.config import Settings

from dimos.experimental.household_assistant.configuration import PilotConfiguration
from dimos.experimental.household_assistant.local_models import ClipEmbeddingAdapter
from dimos.experimental.household_assistant.semantic_memory import HouseholdMemory, load_catalog
from dimos.experimental.household_assistant.visual import HouseholdPerception
from dimos.models.embedding.clip import CLIPModel
from dimos.perception.detection.detectors.yolo import Yolo2DDetector
from dimos.perception.spatial_vector_db import SpatialVectorDB
from dimos.perception.visual_memory import VisualMemory


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class PlannerResources:
    def __init__(
        self, pilot: PilotConfiguration, clip_path: Path, yolo_path: Path, memory_path: Path
    ) -> None:
        self.pilot = pilot
        self.clip_path = clip_path
        self.yolo_path = yolo_path
        self.memory_path = memory_path
        self._clip: CLIPModel | None = None
        self._detector: Yolo2DDetector | None = None
        self.memory: HouseholdMemory
        self.perception: HouseholdPerception

    def start(self) -> None:
        if not (self.clip_path / "model.safetensors").is_file() or not self.yolo_path.is_file():
            raise ValueError("local CLIP and YOLO weights required; no runtime downloads")
        self._clip = CLIPModel(model_name=str(self.clip_path.resolve()), device="cpu")
        try:
            self._detector = Yolo2DDetector(
                model_path=str(self.yolo_path.resolve().parent),
                model_name=self.yolo_path.name,
                device="cpu",
                tracking=False,
            )
            self.perception = HouseholdPerception(
                self._detector, "dimos_yolo:" + file_digest(self.yolo_path)
            )
            embedding = ClipEmbeddingAdapter(self._clip)
            client = chromadb.PersistentClient(
                path=str(self.memory_path), settings=Settings(anonymized_telemetry=False)
            )
            store = SpatialVectorDB(
                collection_name="household_f5",
                chroma_client=client,
                visual_memory=VisualMemory(),
                embedding_provider=embedding,
            )
            self.memory = HouseholdMemory(
                store,
                embedding,
                load_catalog(self.pilot),
                embedding_id="dimos_clip:" + file_digest(self.clip_path / "model.safetensors"),
            )
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._detector is not None:
            self._detector.stop()
            self._detector = None
        if self._clip is not None:
            self._clip.stop()
            self._clip = None
