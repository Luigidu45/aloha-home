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

"""Consume a live or replayed F2 snapshot without station-coordinate lookup."""

from dimos.experimental.household_assistant.spatial_module import SpatialSnapshot
from dimos.experimental.household_assistant.visual import ObservedView, rgb_digest


def view_from_snapshot(
    snapshot: SpatialSnapshot, *, view_id: str, map_id: str, retain_place: bool = True
) -> ObservedView:
    if snapshot.status.pose is None or snapshot.status.state != "arrived":
        raise ValueError("snapshot needs confirmed arrival and localization")
    images = [e for e in snapshot.evidence if e.source == "front_camera_image"]
    poses = [e for e in snapshot.evidence if e.source == "mujoco_ground_truth_localization"]
    if len(images) != 1 or len(poses) != 1:
        raise ValueError("snapshot requires unique image and localization evidence")
    image_evidence, pose_evidence = images[0], poses[0]
    if (
        image_evidence.origin != pose_evidence.origin
        or image_evidence.clock_id != pose_evidence.clock_id
        or pose_evidence.captured_at != snapshot.status.pose.ts
        or pose_evidence.frame_id != snapshot.status.pose.frame_id
    ):
        raise ValueError("incompatible localization evidence")
    view = ObservedView(
        id=view_id,
        evidence=image_evidence,
        rgb_sha256=rgb_digest(snapshot.image),
        observer_pose=snapshot.status.pose,
        pose_source=snapshot.status.localization,
        map_id=map_id,
        place_id=snapshot.status.place_id if retain_place else None,
    )
    view.validate_image(snapshot.image)
    return view
