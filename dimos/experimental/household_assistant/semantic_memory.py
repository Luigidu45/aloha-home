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

"""Mission adapter over DimOS SpatialVectorDB; hints and evidence remain distinct."""

from pathlib import Path
from typing import Any, Literal, Protocol, Self
import unicodedata

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from dimos.experimental.household_assistant.assessment import assess_completion
from dimos.experimental.household_assistant.configuration import PilotConfiguration
from dimos.experimental.household_assistant.contracts import (
    Contract,
    ExecutionReport,
    FactKey,
    Identifier,
    Observation,
    Origin,
    Predicate,
    Text,
    Verdict,
    Verification,
)
from dimos.experimental.household_assistant.visual import (
    AbsenceReview,
    Category,
    ObservedView,
    VisualObservation,
)
from dimos.msgs.sensor_msgs.Image import Image
from dimos.perception.spatial_vector_db import SpatialVectorDB

CATALOG_PATH = Path(__file__).parent / "configs" / "semantic_catalog.json"


def normalize_alias(value: str) -> str:
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", value.casefold())
            if not unicodedata.combining(c)
        )
        .replace("_", " ")
        .split()
    )


class SemanticPlace(Contract):
    place_id: Identifier
    aliases: tuple[Text, ...]
    role: Literal["pickup", "delivery", "floor_pickup"]
    region_description: Text


class ObjectHint(Contract):
    category: Category
    aliases: tuple[Text, ...]
    retrieval_text: Text
    usual_places: tuple[Identifier, ...]


class SemanticCatalog(Contract):
    schema_version: Literal[1]
    places: tuple[SemanticPlace, ...]
    objects: tuple[ObjectHint, ...]

    @model_validator(mode="after")
    def references(self) -> Self:
        place_ids = {p.place_id for p in self.places}
        if len(place_ids) != len(self.places) or len({o.category for o in self.objects}) != len(
            self.objects
        ):
            raise ValueError("duplicate catalog entries")
        for group in (
            [a for p in self.places for a in (p.place_id, *p.aliases)],
            [a for o in self.objects for a in (o.category, *o.aliases)],
        ):
            normalized = [normalize_alias(a) for a in group]
            if len(normalized) != len(set(normalized)):
                raise ValueError("ambiguous aliases")
        if any(not set(o.usual_places) <= place_ids for o in self.objects):
            raise ValueError("unknown usual place")
        return self

    def place(self, name: str) -> SemanticPlace:
        for place in self.places:
            if normalize_alias(name) in {
                normalize_alias(a) for a in (place.place_id, *place.aliases)
            }:
                return place
        raise ValueError("unknown or underspecified place")

    def target(self, name: str) -> ObjectHint:
        for obj in self.objects:
            if normalize_alias(name) in {normalize_alias(a) for a in (obj.category, *obj.aliases)}:
                return obj
        raise ValueError("unknown object category")


def load_catalog(pilot: PilotConfiguration, path: Path = CATALOG_PATH) -> SemanticCatalog:
    catalog = SemanticCatalog.model_validate_json(path.read_text())
    if {p.place_id: p.role for p in catalog.places} != {p.id: p.role for p in pilot.places}:
        raise ValueError("semantic catalog differs from pilot places")
    if {o.category for o in catalog.objects} != {o.category for o in pilot.objects}:
        raise ValueError("semantic catalog differs from pilot categories")
    return catalog


class ImageTextEmbedding(Protocol):
    def image_vector(self, image: Image) -> NDArray[np.float32]: ...
    def get_text_embedding(self, text: str) -> NDArray[np.float32]: ...


class MemoryCandidate(Contract):
    view: ObservedView
    cosine_distance: float
    source: Literal["dimos_spatial_vector_db"] = "dimos_spatial_vector_db"


class PlacementRecord(Contract):
    object_id: Identifier
    place_id: Identifier
    verification: Verification


class HouseholdMemory:
    """Single-owner adapter; the caller owns model/client lifecycle.

    The supplied DimOS store persists embeddings and view metadata. Mission
    observations/reviews are explicit journal inputs; rebuild by replaying them.
    A new session never turns persistent retrieval results into current facts.
    """

    def __init__(
        self,
        store: SpatialVectorDB,
        embedding: ImageTextEmbedding,
        catalog: SemanticCatalog,
        *,
        embedding_id: str,
    ) -> None:
        self.store = store
        self.embedding = embedding
        self.catalog = catalog
        self.embedding_id = embedding_id
        self.observations: list[VisualObservation] = []
        self.absences: list[AbsenceReview] = []
        self.placements: dict[str, PlacementRecord] = {}

    def remember(self, image: Image, view: ObservedView) -> None:
        view.validate_image(image)
        self._validate_embedding_space()
        if self.store.image_collection.get(ids=[view.id])["ids"]:
            raise ValueError("view ID already exists; captures are immutable")
        vector = self.embedding.image_vector(image)
        self.store.add_image_vector(
            view.id,
            image.to_opencv(),
            vector,
            {
                "view": view.model_dump_json(),
                "x": view.observer_pose.x,
                "y": view.observer_pose.y,
                "embedding_id": self.embedding_id,
            },
        )

    def record_observation(self, observation: VisualObservation) -> None:
        self.observations.append(observation)

    def record_absence(self, review: AbsenceReview) -> None:
        self.absences.append(review)

    def _validate_embedding_space(self) -> None:
        metadata = self.store.image_collection.get(include=["metadatas"])["metadatas"]
        if any(
            item is None or item.get("embedding_id") != self.embedding_id for item in metadata or []
        ):
            raise ValueError("incompatible embedding model in collection; use a new collection")

    @staticmethod
    def _same_context(a: ObservedView, b: ObservedView) -> bool:
        return (
            a.map_id == b.map_id
            and a.evidence.clock_id == b.evidence.clock_id
            and a.evidence.origin == b.evidence.origin
            and a.observer_pose.frame_id == b.observer_pose.frame_id
        )

    def contradicted(self, view: ObservedView, category: Category) -> bool:
        return any(
            r.category == category
            and r.view.place_id == view.place_id
            and self._same_context(r.view, view)
            and r.view.evidence.captured_at >= view.evidence.captured_at
            for r in self.absences
        )

    def candidates(
        self, category: Category, *, map_id: str, origin: Origin, clock_id: str, limit: int = 5
    ) -> tuple[MemoryCandidate, ...]:
        if limit < 1:
            raise ValueError("positive candidate limit required")
        self._validate_embedding_space()
        # Filter incompatible/contradicted entries before applying the final limit.
        count = self.store.image_collection.count()
        if not count:
            return ()
        query = self.catalog.target(category).retrieval_text
        vector = self.embedding.get_text_embedding(query)
        results = self.store.query_by_embedding(vector, limit=count)
        candidates = []
        for result in results:
            metadata = result["metadata"]
            if metadata.get("embedding_id") != self.embedding_id:
                raise ValueError("incompatible embedding model in collection")
            view = ObservedView.model_validate_json(metadata["view"])
            if (
                view.map_id != map_id
                or view.evidence.origin != origin
                or view.evidence.clock_id != clock_id
                or self.contradicted(view, category)
            ):
                continue
            candidates.append(MemoryCandidate(view=view, cosine_distance=float(result["distance"])))
            if len(candidates) == limit:
                break
        return tuple(candidates)

    def last_observed(
        self, category: Category, *, map_id: str, origin: Origin, clock_id: str
    ) -> VisualObservation | None:
        eligible = [
            o
            for o in self.observations
            if o.category == category
            and o.candidates
            and o.view.map_id == map_id
            and o.view.evidence.origin == origin
            and o.view.evidence.clock_id == clock_id
            and not self.contradicted(o.view, category)
        ]
        return max(eligible, key=lambda o: o.view.evidence.captured_at, default=None)

    def current(
        self,
        category: Category,
        place_id: str,
        *,
        now: float,
        map_id: str,
        origin: Origin,
        clock_id: str,
        max_age_s: float = 2.0,
    ) -> VisualObservation | None:
        # Latest frame wins, even if it contains no detections; do not revive an older positive.
        eligible = [
            o
            for o in self.observations
            if o.category == category
            and o.view.place_id == place_id
            and o.view.map_id == map_id
            and o.view.evidence.origin == origin
            and o.view.evidence.clock_id == clock_id
        ]
        latest = max(eligible, key=lambda o: o.view.evidence.captured_at, default=None)
        if (
            latest is None
            or self.contradicted(latest.view, category)
            or not latest.is_current(now=now, clock_id=clock_id, max_age_s=max_age_s)
        ):
            return None
        return latest

    def verify_placement(
        self,
        pilot: PilotConfiguration,
        object_id: str,
        place_id: str,
        arm: Literal["left", "right"],
        execution: ExecutionReport,
        observations: tuple[Observation, ...],
        *,
        now: float,
        clock_id: str,
        allowed_origins: frozenset[Origin],
        max_age_s: float = 2.0,
    ) -> Verification:
        if object_id not in {o.id for o in pilot.objects} or place_id not in {
            p.id for p in pilot.places if p.role == "delivery"
        }:
            raise ValueError("unknown object or delivery region")
        required = (
            FactKey(subject_id=object_id, predicate=Predicate.INSIDE, place_id=place_id),
            FactKey(subject_id=object_id, predicate=Predicate.RELEASED, arm=arm),
            FactKey(subject_id="base", predicate=Predicate.STOPPED),
        )
        verification = assess_completion(
            execution,
            required,
            observations,
            now=now,
            clock_id=clock_id,
            max_age_s=max_age_s,
            allowed_origins=allowed_origins,
        )
        if verification.verdict == Verdict.SUCCESS:
            previous = self.placements.get(object_id)
            if previous and min(e.captured_at for e in verification.evidence) <= max(
                e.captured_at for e in previous.verification.evidence
            ):
                return Verification(verdict=Verdict.UNKNOWN, reason="placement_older_than_record")
            self.placements[object_id] = PlacementRecord(
                object_id=object_id, place_id=place_id, verification=verification
            )
        return verification

    def journal(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "observations": [o.model_dump(mode="json") for o in self.observations],
            "absence_reviews": [r.model_dump(mode="json") for r in self.absences],
            "verified_placements": [r.model_dump(mode="json") for r in self.placements.values()],
        }

    def restore_journal(self, payload: dict[str, Any]) -> None:
        """Restore a trusted local journal explicitly before serving mission queries."""
        if self.observations or self.absences or self.placements:
            raise ValueError("restore requires empty mission state")
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported journal version")
        observations = [VisualObservation.model_validate(o) for o in payload["observations"]]
        absences = [AbsenceReview.model_validate(r) for r in payload["absence_reviews"]]
        placements = [PlacementRecord.model_validate(r) for r in payload["verified_placements"]]
        if any(r.verification.verdict != Verdict.SUCCESS for r in placements):
            raise ValueError("journal contains an unverified placement")
        self.observations = observations
        self.absences = absences
        self.placements = {r.object_id: r for r in placements}


class SearchStep(Contract):
    kind: Literal["inspect_candidate", "observe_place", "another_view", "ask_user"]
    place_id: Identifier | None = None
    memory_candidate: MemoryCandidate | None = None
    reason: Text


class BoundedSearch:
    """Deterministic proposals only; F4 owns navigation and observation dispatch."""

    def __init__(
        self,
        hints: ObjectHint,
        candidates: tuple[MemoryCandidate, ...],
        *,
        max_places: int = 3,
        views_per_place: int = 2,
    ) -> None:
        if max_places < 1 or views_per_place < 1:
            raise ValueError("search limits must be positive")
        steps = []
        seen: set[str] = set()
        for candidate in candidates:
            key = candidate.view.place_id or candidate.view.id
            if key in seen:
                continue
            seen.add(key)
            steps.append(
                SearchStep(
                    kind="inspect_candidate",
                    place_id=candidate.view.place_id,
                    memory_candidate=candidate,
                    reason="revisit_observer_pose_then_confirm_pixels",
                )
            )
        for place_id in hints.usual_places:
            if place_id not in seen:
                steps.append(
                    SearchStep(
                        kind="observe_place",
                        place_id=place_id,
                        reason="usual_location_is_only_a_hint",
                    )
                )
        self._steps = steps[:max_places]
        self._index = 0
        self._view = 0
        self._views_per_place = views_per_place
        self._terminal = False

    def next(self, previous: Literal["unknown", "absent", "ambiguous"] | None = None) -> SearchStep:
        if self._terminal or previous == "ambiguous":
            self._terminal = True
            return SearchStep(
                kind="ask_user",
                reason="choose_between_frame_local_candidates"
                if previous == "ambiguous"
                else "search_budget_exhausted",
            )
        if self._index >= len(self._steps):
            self._terminal = True
            return SearchStep(kind="ask_user", reason="search_budget_exhausted")
        step = self._steps[self._index]
        if previous == "unknown" and self._view < self._views_per_place:
            self._view += 1
            return SearchStep(
                kind="another_view",
                place_id=step.place_id,
                memory_candidate=step.memory_candidate,
                reason="occlusion_or_detector_miss_requires_new_evidence",
            )
        if previous is not None:
            self._index += 1
            self._view = 0
            return self.next()
        if self._view:
            raise ValueError(
                "provide the previous observation result before requesting another step"
            )
        self._view = 1
        return step
