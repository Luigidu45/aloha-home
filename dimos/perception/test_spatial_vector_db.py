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

"""Regression coverage for retrieving multiple spatial neighbors."""

import uuid

import chromadb
from chromadb.config import Settings
import numpy as np
import pytest

from dimos.perception.spatial_vector_db import SpatialVectorDB
from dimos.perception.visual_memory import VisualMemory


@pytest.fixture
def spatial_db():
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
    name = f"test_{uuid.uuid4().hex}"
    store = SpatialVectorDB(
        collection_name=name, chroma_client=client, visual_memory=VisualMemory()
    )
    try:
        yield store
    finally:
        client.delete_collection(name)
        client.delete_collection(f"{name}_locations")


def test_query_returns_each_neighbor_with_its_own_metadata(spatial_db):
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    spatial_db.add_image_vector("near", image, np.array([1.0, 0.0]), {"x": 1.0, "y": 0.0})
    spatial_db.add_image_vector("far", image, np.array([0.0, 1.0]), {"x": 2.0, "y": 0.0})

    results = spatial_db.query_by_embedding(np.array([1.0, 0.0]), limit=2)

    assert [r["id"] for r in results] == ["near", "far"]
    assert [r["metadata"]["x"] for r in results] == [1.0, 2.0]
    assert [r["distance"] for r in results] == pytest.approx([0.0, 1.0])
    assert [r["id"] for r in spatial_db.query_by_location(0, 0, radius=3)] == ["near", "far"]


def test_empty_query_and_optional_metadata(spatial_db):
    assert spatial_db.query_by_embedding(np.array([1.0, 0.0])) == []
    spatial_db.image_collection.add(ids=["no_metadata"], embeddings=[[1.0, 0.0]])
    assert spatial_db.query_by_embedding(np.array([1.0, 0.0]))[0]["metadata"] == {}
