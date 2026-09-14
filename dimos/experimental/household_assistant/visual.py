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

"""RGB evidence and frame-local candidates; no instance identity or metric grasp pose."""

import hashlib
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, model_validator

from dimos.experimental.household_assistant.contracts import Contract, Evidence, Identifier, Text
from dimos.experimental.household_assistant.spatial import PoseSample
from dimos.msgs.sensor_msgs.Image import Image
from dimos.perception.detection.type.detection2d.imageDetections2D import ImageDetections2D

Category = Literal["small_bottle", "remote_control"]


def rgb_digest(image: Image) -> str:
    rgb = image.to_rgb().data
    return hashlib.sha256(str(rgb.shape).encode() + rgb.tobytes()).hexdigest()


class ObservedView(Contract):
    id: Identifier
    evidence: Evidence
    rgb_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    observer_pose: PoseSample
    pose_source: Text
    map_id: Identifier
    place_id: Identifier | None = None

    @model_validator(mode="after")
    def synchronized_pose(self) -> Self:
        if abs(self.observer_pose.ts - self.evidence.captured_at) > 0.5:
            raise ValueError("observer pose is not synchronized with the image")
        if not self.observer_pose.frame_id:
            raise ValueError("observer pose requires a reference frame")
        return self

    def validate_image(self, image: Image) -> None:
        if (
            image.ts != self.evidence.captured_at
            or image.frame_id != self.evidence.frame_id
            or rgb_digest(image) != self.rgb_sha256
        ):
            raise ValueError("image does not match its evidence")


class PixelCandidate(Contract):
    id: Identifier
    category: Category
    bbox_xyxy: tuple[float, float, float, float]
    score: Annotated[float, Field(ge=0, le=1)]

    @model_validator(mode="after")
    def ordered_box(self) -> Self:
        x1, y1, x2, y2 = self.bbox_xyxy
        if not (0 <= x1 < x2 and 0 <= y1 < y2):
            raise ValueError("invalid pixel box")
        return self


class VisualObservation(Contract):
    view: ObservedView
    category: Category
    model: Text
    candidates: tuple[PixelCandidate, ...] = ()
    status: Literal["candidate", "ambiguous", "unknown"]
    reason: Text

    @model_validator(mode="after")
    def consistent_candidates(self) -> Self:
        expected = (
            "ambiguous"
            if len(self.candidates) > 1
            else "candidate"
            if self.candidates
            else "unknown"
        )
        if self.status != expected or any(c.category != self.category for c in self.candidates):
            raise ValueError("inconsistent visual result")
        if len({c.id for c in self.candidates}) != len(self.candidates):
            raise ValueError("duplicate frame-local candidates")
        return self

    def is_current(self, *, now: float, clock_id: str, max_age_s: float = 2.0) -> bool:
        return (
            self.view.evidence.clock_id == clock_id
            and 0 <= now - self.view.evidence.captured_at <= max_age_s
        )


class PixelDetector(Protocol):
    def process_image(self, image: Image) -> ImageDetections2D: ...


class HouseholdPerception:
    """Adapt DimOS detector outputs. No annotations, simulator or place catalog access."""

    def __init__(self, detector: PixelDetector, model_id: str) -> None:
        self.detector = detector
        self.model_id = model_id

    def observe(self, image: Image, view: ObservedView, category: Category) -> VisualObservation:
        view.validate_image(image)
        result = self.detector.process_image(image)
        expected_label = {"small_bottle": "bottle", "remote_control": "remote"}[category]
        width, height = image.to_rgb().data.shape[1], image.to_rgb().data.shape[0]
        compatible = sorted(
            (d for d in result.detections if d.name == expected_label), key=lambda d: d.bbox[0]
        )
        candidates = tuple(
            PixelCandidate(
                id=f"{view.id}_candidate_{i}",
                category=category,
                bbox_xyxy=(
                    max(0.0, d.bbox[0]),
                    max(0.0, d.bbox[1]),
                    min(float(width), d.bbox[2]),
                    min(float(height), d.bbox[3]),
                ),
                score=d.confidence,
            )
            for i, d in enumerate(compatible)
        )
        return VisualObservation(
            view=view,
            category=category,
            model=self.model_id,
            candidates=candidates,
            status="ambiguous" if len(candidates) > 1 else "candidate" if candidates else "unknown",
            reason="multiple_compatible_objects"
            if len(candidates) > 1
            else "category_candidate_not_instance_identity"
            if candidates
            else "no_detection_does_not_prove_absence",
        )


class AbsenceReview(Contract):
    """Explicit operator review of this view, never inferred from a detector miss.

    Scope is the inspected region, not the room. Occluded or incomplete regions
    must not receive this record. Calling code supplies the operator's evidence.
    """

    view: ObservedView
    category: Category
    reviewer: Text
    region_fully_visible: Literal[True]
    target_absent: Literal[True]
    reviewed_at: Annotated[float, Field(ge=0)]
    note: Text

    @model_validator(mode="after")
    def after_capture(self) -> Self:
        if self.reviewed_at < self.view.evidence.captured_at or self.view.place_id is None:
            raise ValueError("absence review needs a named inspected region and capture time")
        return self
