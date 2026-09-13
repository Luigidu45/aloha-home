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

"""Read F2 sensor recordings offline without changing their original timestamps."""

import argparse
from collections.abc import Iterator
import hashlib
import json
from pathlib import Path

import numpy as np

from dimos.experimental.household_assistant.contracts import Evidence, Origin
from dimos.experimental.household_assistant.spatial import SpatialStatus
from dimos.experimental.household_assistant.spatial_module import SpatialSnapshot
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2


def load_snapshots(directory: Path) -> Iterator[SpatialSnapshot]:
    report = json.loads((directory / "report.json").read_text())
    if report["origin"] != "simulation" or report["clock_id"] != "unix":
        raise ValueError("unsupported recording provenance")
    for entry in report["snapshots"]:
        path = (directory / entry["arrays"]).resolve()
        if path.parent != directory.resolve():
            raise ValueError("recording array path must be local")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("recording checksum mismatch")
        evidence = tuple(Evidence.model_validate(item) for item in entry["evidence"])
        by_source = {item.source: item for item in evidence}
        if (
            set(by_source)
            != {"mujoco_ground_truth_localization", "front_camera_image", "raycast_pointcloud"}
            or len(evidence) != 3
            or any(item.origin != Origin.SIMULATION or item.clock_id != "unix" for item in evidence)
        ):
            raise ValueError("incompatible sensor evidence")
        image_evidence = by_source["front_camera_image"]
        cloud_evidence = by_source["raycast_pointcloud"]
        with np.load(path, allow_pickle=False) as arrays:
            rgb, points = arrays["rgb"], arrays["points"]
            if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
                raise ValueError("invalid RGB recording")
            if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
                raise ValueError("invalid pointcloud recording")
            yield SpatialSnapshot(
                status=SpatialStatus.model_validate(entry["status"]),
                image=Image(
                    data=rgb,
                    format=ImageFormat.RGB,
                    ts=image_evidence.captured_at,
                    frame_id=image_evidence.frame_id,
                ),
                pointcloud=PointCloud2.from_numpy(
                    points, frame_id=cloud_evidence.frame_id, timestamp=cloud_evidence.captured_at
                ),
                evidence=evidence,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    for snapshot in load_snapshots(args.directory):
        print(
            json.dumps(
                {
                    "place_id": snapshot.status.place_id,
                    "origin": "simulation",
                    "captured_at": snapshot.image.ts,
                    "frame_id": snapshot.image.frame_id,
                    "point_count": len(snapshot.pointcloud.as_numpy()[0]),
                }
            )
        )


if __name__ == "__main__":
    main()
