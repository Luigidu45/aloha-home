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

"""Behavioral checks for station arrival, stop evidence and sensor freshness."""

import math

import numpy as np
import pytest

from dimos.experimental.household_assistant.spatial import (
    PoseSample,
    PoseWindow,
    load_spatial,
    within_approach,
)
from dimos.experimental.household_assistant.spatial_module import HouseholdSpatialModule
from dimos.msgs.geometry_msgs.PoseStamped import PoseStamped
from dimos.msgs.geometry_msgs.Quaternion import Quaternion
from dimos.msgs.geometry_msgs.Vector3 import Vector3
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat
from dimos.msgs.sensor_msgs.PointCloud2 import PointCloud2
from dimos.navigation.navigation_spec import NavigationInterfaceSpec


@pytest.fixture
def pose_window():
    return PoseWindow(
        settle_s=0.5, max_age_s=1.0, linear_stop_mps=0.03, angular_stop_rps=0.05, frame_id="world"
    )


def test_duplicate_pose_does_not_prove_stop(pose_window):
    sample = PoseSample(ts=10.0, x=0, y=0, yaw=0, frame_id="world")
    for _ in range(20):
        pose_window.add(sample)
    assert not pose_window.stopped(10.8, after=9.0)


def test_rotation_is_motion_even_at_fixed_position(pose_window):
    for i in range(8):
        pose_window.add(PoseSample(ts=10 + i * 0.1, x=0, y=0, yaw=i * 0.1, frame_id="world"))
    assert not pose_window.stopped(10.7, after=9.0)


def test_stationary_samples_require_freshness_and_post_stop_timing(pose_window):
    for i in range(8):
        pose_window.add(PoseSample(ts=10 + i * 0.1, x=1, y=2, yaw=0, frame_id="world"))
    assert pose_window.stopped(10.7, after=9.0)
    assert not pose_window.stopped(12.0, after=9.0)
    assert not pose_window.stopped(10.7, after=10.5)
    assert not pose_window.stopped(9.0, after=8.0)


def test_orientation_wraps_at_pi():
    target = load_spatial().approach("mesa_sala", "observe").model_copy(update={"yaw": math.pi})
    pose = PoseSample(ts=10, x=target.x, y=target.y, yaw=-math.pi + 0.01, frame_id="world")
    assert within_approach(pose, target)


@pytest.fixture
def adapter(mocker):
    module = HouseholdSpatialModule(navigation_timeout_s=3.0)
    navigator = mocker.Mock(spec=NavigationInterfaceSpec)
    navigator.set_goal.return_value = True
    navigator.is_goal_reached.return_value = False
    mocker.patch.object(module, "_navigation", navigator, create=True)
    # Exercise callbacks/ticks with deterministic timestamps instead of a timer thread.
    mocker.patch.object(module, "_run")
    for stream in module.inputs.values():
        mocker.patch.object(stream, "subscribe", return_value=lambda: None)
    mocker.patch(
        "dimos.experimental.household_assistant.spatial_module.time.time", return_value=100.0
    )
    module.start()
    yield module, navigator
    module.stop()


def feed_pose(module, ts, *, x=-2.5, y=0.5, yaw=math.pi / 2, frame="world"):
    module._on_pose(
        PoseStamped(
            ts=ts,
            frame_id=frame,
            position=Vector3(x, y, 0),
            orientation=Quaternion.from_euler(Vector3(0, 0, yaw)),
        )
    )


def settle(module, start, *, x=-2.5, y=0.5):
    for i in range(1, 9):
        feed_pose(module, start + i * 0.1, x=x, y=y)
    module._tick(start + 0.8)


def test_unknown_destination_never_reaches_planner(adapter):
    module, navigator = adapter
    feed_pose(module, 100)
    with pytest.raises(ValueError, match="unknown spatial station"):
        module.go_to("kitchen")
    navigator.set_goal.assert_not_called()


def test_stale_or_wrong_frame_localization_cannot_start(adapter):
    module, navigator = adapter
    feed_pose(module, 100, frame="map")
    with pytest.raises(RuntimeError, match="fresh"):
        module.go_to("mesa_sala")
    feed_pose(module, 90)
    with pytest.raises(RuntimeError, match="fresh"):
        module.go_to("mesa_sala")
    navigator.set_goal.assert_not_called()


def test_semantic_goal_selects_distinct_observation_and_manipulation_poses(adapter):
    module, navigator = adapter
    feed_pose(module, 100)
    module.go_to("mesa_sala", "manipulate")
    goal = navigator.set_goal.call_args.args[0]
    assert goal.position.x == -2.5
    assert goal.position.y == 0.65
    assert goal.frame_id == "world"
    assert goal.orientation.euler[2] == pytest.approx(math.pi / 2)
    with pytest.raises(RuntimeError, match="previous navigation"):
        module.go_to("mesa_dormitorio")
    assert navigator.set_goal.call_count == 1


def test_planner_done_requires_pose_and_observed_stop(adapter):
    module, navigator = adapter
    feed_pose(module, 100)
    module.go_to("mesa_sala")
    navigator.is_goal_reached.return_value = True
    module._tick(100.1)
    assert module.get_status().state == "stopping"
    settle(module, 100.1)
    assert module.get_status().state == "arrived"


def test_planner_shifted_goal_is_not_arrival_at_requested_station(adapter):
    module, navigator = adapter
    feed_pose(module, 100, y=-0.8)
    module.go_to("mesa_sala")
    navigator.is_goal_reached.return_value = True
    module._tick(100.1)
    settle(module, 100.1, y=-0.8)
    assert module.get_status().state == "failed"
    assert module.get_status().reason == "planner_arrived_outside_station"


def test_cancel_waits_for_stop_and_rejects_another_goal(adapter):
    module, navigator = adapter
    feed_pose(module, 100)
    module.go_to("mesa_dormitorio")
    assert module.cancel().state == "stopping"
    navigator.cancel_goal.assert_called_once_with()
    with pytest.raises(RuntimeError, match="previous navigation"):
        module.go_to("mesa_sala")
    settle(module, 100)
    assert module.get_status().state == "cancelled"


def test_missing_stop_evidence_stays_unconfirmed_and_blocks_restart(adapter):
    module, _ = adapter
    feed_pose(module, 100)
    module.go_to("mesa_sala")
    module.cancel()
    module._tick(106)
    assert module.get_status().state == "stop_unconfirmed"
    with pytest.raises(RuntimeError, match="previous navigation"):
        module.go_to("mesa_dormitorio")


def test_blocked_timeout_cancels_then_confirms_failure(adapter):
    module, navigator = adapter
    feed_pose(module, 100)
    module.go_to("mesa_dormitorio")
    feed_pose(module, 104)
    module._tick(104)
    assert module.get_status().state == "stopping"
    navigator.cancel_goal.assert_called_once_with()
    settle(module, 104)
    assert module.get_status().state == "failed"
    assert module.get_status().reason == "navigation_timeout_or_blocked"


def test_station_snapshot_requires_post_arrival_image_and_cloud(adapter, mocker):
    module, navigator = adapter
    feed_pose(module, 100)
    module.go_to("mesa_sala")
    navigator.is_goal_reached.return_value = True
    module._tick(100)
    settle(module, 100)
    settle(module, 100.8)
    mocker.patch(
        "dimos.experimental.household_assistant.spatial_module.time.time", return_value=101.6
    )
    cloud = PointCloud2.from_numpy(np.array([[1.0, 2.0, 0.5]]), frame_id="world", timestamp=101.5)
    module._on_cloud(cloud)
    module._on_image(
        Image(
            data=np.ones((2, 2, 3), dtype=np.uint8),
            format=ImageFormat.RGB,
            frame_id="front_camera_color_optical_frame",
            ts=100.5,
        )
    )
    assert module.get_observation("mesa_sala") is None
    module._on_image(
        Image(
            data=np.ones((2, 2, 3), dtype=np.uint8),
            format=ImageFormat.RGB,
            frame_id="front_camera_color_optical_frame",
            ts=101.5,
        )
    )
    snapshot = module.get_observation("mesa_sala")
    assert snapshot is not None
    assert [item.source for item in snapshot.evidence] == [
        "mujoco_ground_truth_localization",
        "front_camera_image",
        "raycast_pointcloud",
    ]
    assert snapshot.evidence[1].captured_at == 101.5
    assert module.get_observation("mesa_dormitorio") is None
    mocker.patch(
        "dimos.experimental.household_assistant.spatial_module.time.time", return_value=105.0
    )
    assert module.get_observation("mesa_sala") is None
