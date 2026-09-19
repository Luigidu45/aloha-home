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

"""Mission memory behavior with a real DimOS/Chroma store and mocked model boundary."""

import uuid

import chromadb
from chromadb.config import Settings
import numpy as np
import pytest

from dimos.experimental.household_assistant.contracts import (
    Evidence,
    ExecutionReport,
    ExecutionStage,
    FactKey,
    Observation,
    Origin,
    Predicate,
    Verdict,
)
from dimos.experimental.household_assistant.mission import MissionManager
from dimos.experimental.household_assistant.mission_sequence import (
    MissionSequence,
    record_verified_placement,
)
from dimos.experimental.household_assistant.mission_simulation import (
    ArtificialMissionExecutor,
    simulation_bindings,
)
from dimos.experimental.household_assistant.mission_visual import visibility_from_visual
from dimos.experimental.household_assistant.semantic_memory import (
    BoundedSearch,
    HouseholdMemory,
    MemoryCandidate,
    load_catalog,
)
from dimos.experimental.household_assistant.spatial import PoseSample
from dimos.experimental.household_assistant.visual import (
    AbsenceReview,
    ObservedView,
    PixelCandidate,
    VisualObservation,
    rgb_digest,
)
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat
from dimos.perception.spatial_vector_db import SpatialVectorDB
from dimos.perception.visual_memory import VisualMemory


@pytest.fixture
def memory(pilot, mocker):
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
    name = f"test_{uuid.uuid4().hex}"
    store = SpatialVectorDB(
        collection_name=name, chroma_client=client, visual_memory=VisualMemory()
    )
    embedding = mocker.Mock()
    embedding.image_vector.return_value = np.array([1.0, 0.0], dtype=np.float32)
    embedding.get_text_embedding.return_value = np.array([1.0, 0.0], dtype=np.float32)
    try:
        yield HouseholdMemory(store, embedding, load_catalog(pilot), embedding_id="test_embedding")
    finally:
        client.delete_collection(name)
        client.delete_collection(f"{name}_locations")


def capture(view_id="old", ts=10.0, place_id="mesa_sala", origin=Origin.TEST, clock_id="test"):
    image = Image(
        data=np.zeros((16, 16, 3), dtype=np.uint8), format=ImageFormat.RGB, ts=ts, frame_id="rgb"
    )
    view = ObservedView(
        id=view_id,
        evidence=Evidence(
            origin=origin,
            source="fixture",
            reference=view_id,
            captured_at=ts,
            clock_id=clock_id,
            frame_id="rgb",
        ),
        rgb_sha256=rgb_digest(image),
        observer_pose=PoseSample(ts=ts, x=4.2, y=3.1, yaw=0.7, frame_id="world"),
        pose_source="fixture",
        map_id="test",
        place_id=place_id,
    )
    return image, view


def positive(view):
    return VisualObservation(
        view=view,
        category="small_bottle",
        model="test_detector",
        status="candidate",
        reason="fixture",
        candidates=(
            PixelCandidate(
                id=f"{view.id}_candidate_0",
                category="small_bottle",
                bbox_xyxy=(1, 1, 4, 9),
                score=0.8,
            ),
        ),
    )


def review(view):
    return AbsenceReview(
        view=view,
        category="small_bottle",
        reviewer="test_operator",
        region_fully_visible=True,
        target_absent=True,
        reviewed_at=view.evidence.captured_at + 1,
        note="fixture, not physical evidence",
    )


def test_catalog_resolves_aliases_but_does_not_invent_room_destinations(memory):
    assert memory.catalog.place("REGIÓN de entrega").place_id == "mesa_dormitorio"
    assert memory.catalog.target("control remoto").usual_places == ("suelo_sala",)
    with pytest.raises(ValueError, match="underspecified"):
        memory.catalog.place("dormitorio")


def test_memory_recovers_observer_pose_without_registered_place(memory):
    image, view = capture(place_id=None)
    memory.remember(image, view)
    result = memory.candidates("small_bottle", map_id="test", origin=Origin.TEST, clock_id="test")
    assert result[0].view.observer_pose == view.observer_pose
    assert result[0].view.place_id is None
    assert (
        memory.current(
            "small_bottle", "mesa_sala", now=10, map_id="test", origin=Origin.TEST, clock_id="test"
        )
        is None
    )
    with pytest.raises(ValueError, match="already exists"):
        memory.remember(image, view)


def test_negative_current_review_invalidates_old_location_but_not_new_sighting(memory):
    image, old = capture()
    memory.remember(image, old)
    memory.record_observation(positive(old))
    _, absent = capture("absence", 20)
    memory.record_absence(review(absent))
    assert (
        memory.candidates("small_bottle", map_id="test", origin=Origin.TEST, clock_id="test") == ()
    )
    assert (
        memory.last_observed("small_bottle", map_id="test", origin=Origin.TEST, clock_id="test")
        is None
    )
    assert memory.catalog.target("botella").usual_places == ("mesa_sala", "mesa_dormitorio")
    image, new = capture("new", 30)
    memory.remember(image, new)
    memory.record_observation(positive(new))
    assert [
        c.view.id
        for c in memory.candidates(
            "small_bottle", map_id="test", origin=Origin.TEST, clock_id="test"
        )
    ] == ["new"]
    assert (
        memory.last_observed(
            "small_bottle", map_id="test", origin=Origin.TEST, clock_id="test"
        ).view.id
        == "new"
    )


def test_occlusion_does_not_erase_history_or_revive_old_positive_as_current(memory):
    _, old = capture()
    _, new = capture("occluded", 11)
    memory.record_observation(positive(old))
    memory.record_observation(
        VisualObservation(
            view=new, category="small_bottle", model="test", status="unknown", reason="no_detection"
        )
    )
    assert (
        memory.last_observed(
            "small_bottle", map_id="test", origin=Origin.TEST, clock_id="test"
        ).view.id
        == "old"
    )
    assert (
        memory.current(
            "small_bottle", "mesa_sala", now=11, map_id="test", origin=Origin.TEST, clock_id="test"
        ).status
        == "unknown"
    )
    assert (
        memory.current(
            "small_bottle", "mesa_sala", now=14, map_id="test", origin=Origin.TEST, clock_id="test"
        )
        is None
    )


@pytest.mark.parametrize("origin,clock_id", [(Origin.SIMULATION, "test"), (Origin.TEST, "unix")])
def test_review_from_different_context_cannot_invalidate_history(memory, origin, clock_id):
    image, old = capture()
    memory.remember(image, old)
    _, other = capture("other", 20, origin=origin, clock_id=clock_id)
    memory.record_absence(review(other))
    assert (
        len(memory.candidates("small_bottle", map_id="test", origin=Origin.TEST, clock_id="test"))
        == 1
    )


def test_search_budget_alternate_view_and_user_query(memory):
    search = BoundedSearch(memory.catalog.target("botella"), (), max_places=1, views_per_place=2)
    assert search.next().kind == "observe_place"
    assert search.next("unknown").kind == "another_view"
    assert search.next("unknown").kind == "ask_user"
    assert search.next().kind == "ask_user"


def test_ambiguous_objects_require_selection_instead_of_first_candidate(memory):
    _, view = capture(place_id=None)
    candidate = MemoryCandidate(view=view, cosine_distance=0.2)
    search = BoundedSearch(memory.catalog.target("botella"), (candidate,))
    assert search.next().memory_candidate.view.observer_pose == view.observer_pose
    assert search.next("ambiguous").reason == "choose_between_frame_local_candidates"


@pytest.mark.parametrize(
    "stage,value,ts,expected",
    [
        (ExecutionStage.RUNNING, True, 11, Verdict.UNKNOWN),
        (ExecutionStage.FINISHED, None, 11, Verdict.UNKNOWN),
        (ExecutionStage.FINISHED, False, 11, Verdict.FAILURE),
        (ExecutionStage.FINISHED, True, 9, Verdict.UNKNOWN),
        (ExecutionStage.FINISHED, True, 11, Verdict.SUCCESS),
    ],
)
def test_location_changes_only_after_verified_placement(memory, pilot, stage, value, ts, expected):
    execution = ExecutionReport(
        action_id="place", stage=stage, recorded_at=10, clock_id="test", detail="fixture"
    )
    evidence = Evidence(
        origin=Origin.TEST,
        source="fixture",
        reference="placement",
        captured_at=ts,
        clock_id="test",
        frame_id="world",
    )
    facts = (
        FactKey(subject_id="bottle_01", predicate=Predicate.INSIDE, place_id="mesa_dormitorio"),
        FactKey(subject_id="bottle_01", predicate=Predicate.RELEASED, arm="right"),
        FactKey(subject_id="base", predicate=Predicate.STOPPED),
    )
    observations = tuple(Observation(key=key, value=value, evidence=(evidence,)) for key in facts)
    result = memory.verify_placement(
        pilot,
        "bottle_01",
        "mesa_dormitorio",
        "right",
        execution,
        observations,
        now=12,
        clock_id="test",
        allowed_origins=frozenset({Origin.TEST}),
    )
    assert result.verdict == expected
    assert ("bottle_01" in memory.placements) == (expected == Verdict.SUCCESS)


def test_restoring_journal_preserves_invalidations_and_capture_age(memory):
    image, old = capture()
    memory.remember(image, old)
    memory.record_observation(positive(old))
    _, absent = capture("absence", 20)
    memory.record_absence(review(absent))
    restored = HouseholdMemory(
        memory.store, memory.embedding, memory.catalog, embedding_id="test_embedding"
    )
    restored.restore_journal(memory.journal())
    assert (
        restored.candidates("small_bottle", map_id="test", origin=Origin.TEST, clock_id="test")
        == ()
    )
    assert restored.observations[0].view.evidence.captured_at == 10
    with pytest.raises(ValueError, match="empty mission state"):
        restored.restore_journal(memory.journal())


def test_changing_embedding_model_requires_new_collection(memory):
    image, view = capture()
    memory.remember(image, view)
    changed = HouseholdMemory(
        memory.store, memory.embedding, memory.catalog, embedding_id="different_model"
    )
    with pytest.raises(ValueError, match="incompatible embedding"):
        changed.candidates("small_bottle", map_id="test", origin=Origin.TEST, clock_id="test")


def test_f4_only_verified_delivery_updates_f3_memory(memory, pilot, request_a):
    manager = MissionManager(pilot, simulation_bindings(pilot), clock_id="test")
    executor = ArtificialMissionExecutor(manager)
    first = executor.step(now=100)
    manager.submit(request_a, now=100)
    sequence = MissionSequence(manager, request_a)
    refused = record_verified_placement(memory, manager, first, now=100)
    assert refused.verdict == Verdict.UNKNOWN
    assert memory.placements == {}
    for i in range(1, 200):
        now = 100 + i * 0.1
        frame = executor.step(now=now)
        sequence.advance(frame, now=now)
        if manager.snapshot().state == "succeeded":
            break
    assert manager.snapshot().state == "succeeded"
    verified = record_verified_placement(memory, manager, frame, now=now)
    assert verified.verdict == Verdict.SUCCESS
    assert memory.placements["bottle_01"].place_id == "mesa_dormitorio"
    assert {e.origin for e in verified.evidence} == {Origin.TEST}
    assert memory.journal()["verified_placements"][0]["object_id"] == "bottle_01"


def test_f3_visibility_preserves_unknown_instances_and_capture_clock(pilot):
    _, view = capture("current", 10)
    observation = VisualObservation(
        view=view,
        category="small_bottle",
        model="test_detector",
        candidates=(
            PixelCandidate(
                id="pixel_a", category="small_bottle", bbox_xyxy=(1, 1, 5, 5), score=0.9
            ),
        ),
        status="candidate",
        reason="frame_local",
    )
    facts = visibility_from_visual(pilot, observation, {"pixel_a": "bottle_01"})
    assert [(f.key.subject_id, f.value) for f in facts] == [
        ("bottle_01", True),
        ("bottle_02", None),
    ]
    assert all(f.key.predicate == Predicate.VISIBLE for f in facts)
    assert all(f.evidence == (view.evidence,) for f in facts)
    with pytest.raises(ValueError, match="this frame"):
        visibility_from_visual(pilot, observation, {"old_frame_candidate": "bottle_01"})
