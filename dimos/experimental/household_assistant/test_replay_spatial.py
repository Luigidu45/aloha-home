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

import json

import numpy as np
import pytest

from dimos.experimental.household_assistant.contracts import Evidence, Origin
from dimos.experimental.household_assistant.demo_spatial import save_snapshot
from dimos.experimental.household_assistant.replay_spatial import load_snapshots
from dimos.experimental.household_assistant.spatial import SpatialStatus
from dimos.experimental.household_assistant.spatial_module import SpatialSnapshot
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2


@pytest.fixture
def recording(tmp_path):
    image = Image(
        data=np.full((2, 2, 3), 42, dtype=np.uint8),
        format=ImageFormat.RGB,
        frame_id="front_camera_color_optical_frame",
        ts=10.0,
    )
    cloud = PointCloud2.from_numpy(np.array([[1.0, 2.0, 3.0]]), frame_id="world", timestamp=10.1)
    evidence = tuple(
        Evidence(
            origin=Origin.SIMULATION,
            source=source,
            reference=source,
            captured_at=ts,
            clock_id="unix",
            frame_id=frame,
        )
        for source, ts, frame in [
            ("mujoco_ground_truth_localization", 10.2, "world"),
            ("front_camera_image", 10.0, image.frame_id),
            ("raycast_pointcloud", 10.1, "world"),
        ]
    )
    snapshot = SpatialSnapshot(
        status=SpatialStatus(place_id="mesa_sala", state="arrived", ts=10.2),
        image=image,
        pointcloud=cloud,
        evidence=evidence,
    )
    entry = save_snapshot(snapshot, tmp_path)
    (tmp_path / "report.json").write_text(
        json.dumps({"origin": "simulation", "clock_id": "unix", "snapshots": [entry]})
    )
    return tmp_path


def test_replay_preserves_original_sensor_times_and_values(recording):
    snapshots = list(load_snapshots(recording))
    assert len(snapshots) == 1
    assert snapshots[0].image.ts == 10.0
    assert snapshots[0].pointcloud.ts == 10.1
    np.testing.assert_array_equal(snapshots[0].image.data, np.full((2, 2, 3), 42, dtype=np.uint8))
    np.testing.assert_array_equal(snapshots[0].pointcloud.as_numpy()[0], [[1.0, 2.0, 3.0]])


def test_replay_rejects_modified_sensor_data(recording):
    (recording / "mesa_sala.npz").write_bytes(b"modified")
    with pytest.raises(ValueError, match="checksum"):
        list(load_snapshots(recording))
