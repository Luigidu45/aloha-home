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

"""Pixel evidence must survive model adaptation without fabricated identity."""

from dataclasses import replace

import numpy as np
import pytest

from dimos.experimental.household_assistant.contracts import Evidence, Origin
from dimos.experimental.household_assistant.spatial import PoseSample
from dimos.experimental.household_assistant.visual import (
    HouseholdPerception,
    ObservedView,
    rgb_digest,
)
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat
from dimos.perception.detection.type.detection2d.bbox import Detection2DBBox
from dimos.perception.detection.type.detection2d.imageDetections2D import ImageDetections2D


@pytest.fixture
def image_view():
    image = Image(
        data=np.zeros((32, 64, 3), dtype=np.uint8), format=ImageFormat.RGB, ts=10.0, frame_id="rgb"
    )
    view = ObservedView(
        id="frame_a",
        evidence=Evidence(
            origin=Origin.TEST,
            source="fixture",
            reference="fixture_a",
            captured_at=10,
            clock_id="test",
            frame_id="rgb",
        ),
        rgb_sha256=rgb_digest(image),
        observer_pose=PoseSample(ts=10, x=1, y=2, yaw=0, frame_id="world"),
        pose_source="test",
        map_id="test",
        place_id="mesa_sala",
    )
    return image, view


def test_two_bottles_are_distinct_candidates_without_persistent_identity(image_view, mocker):
    image, view = image_view
    bottle = Detection2DBBox(
        bbox=(2, 2, 12, 25),
        track_id=23,
        class_id=39,
        confidence=0.7,
        name="bottle",
        ts=10,
        image=image,
    )
    other = replace(bottle, bbox=(35, 2, 45, 25), track_id=99)
    cup = replace(bottle, name="cup")
    detector = mocker.Mock()
    detector.process_image.return_value = ImageDetections2D(
        image=image, detections=[other, cup, bottle]
    )

    result = HouseholdPerception(detector, "fixture_detector").observe(image, view, "small_bottle")

    assert result.status == "ambiguous"
    assert [c.id for c in result.candidates] == ["frame_a_candidate_0", "frame_a_candidate_1"]
    assert [c.bbox_xyxy[0] for c in result.candidates] == [2, 35]
    assert result.view.evidence == view.evidence
    assert not result.is_current(now=20, clock_id="test")


def test_detector_miss_stays_unknown_even_with_recent_image(image_view, mocker):
    image, view = image_view
    detector = mocker.Mock()
    detector.process_image.return_value = ImageDetections2D(image=image, detections=[])
    result = HouseholdPerception(detector, "fixture_detector").observe(image, view, "small_bottle")
    assert result.status == "unknown"
    assert result.is_current(now=11, clock_id="test")
    assert not result.is_current(now=11, clock_id="unix")


@pytest.mark.parametrize("change", ["pixels", "timestamp", "frame"])
def test_mismatched_capture_never_reaches_detector(image_view, mocker, change):
    image, view = image_view
    altered = Image(
        data=np.ones((32, 64, 3), dtype=np.uint8) if change == "pixels" else image.data,
        format=ImageFormat.RGB,
        ts=11 if change == "timestamp" else 10,
        frame_id="other" if change == "frame" else "rgb",
    )
    detector = mocker.Mock()
    with pytest.raises(ValueError, match="image does not match"):
        HouseholdPerception(detector, "fixture_detector").observe(altered, view, "small_bottle")
    detector.process_image.assert_not_called()
