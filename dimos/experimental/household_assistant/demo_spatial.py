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

"""Record a real headless DimOS/MuJoCo F2 route and failure cases."""

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import time
from typing import Any, cast

import numpy as np

from dimos.constants import DIMOS_PROJECT_ROOT, RECORDINGS_DIR
from dimos.core.coordination.module_coordinator import ModuleCoordinator
from dimos.core.global_config import TransportBackend, global_config
from dimos.experimental.household_assistant.spatial import SPATIAL_SIM_CONFIG, SpatialStatus
from dimos.experimental.household_assistant.spatial_module import (
    HouseholdSpatialModule,
    SpatialSnapshot,
)
from dimos.navigation.replanning_a_star.module import ReplanningAStarPlanner
from dimos.robot.alohamini2.blueprints.household_navigation_sim import household_navigation_sim
from dimos.robot.alohamini2.config import ALOHA_MINI2_NAV_MJCF
from dimos.utils.testing.waiting import wait_until


def save_snapshot(snapshot: SpatialSnapshot, directory: Path) -> dict[str, Any]:
    stem = snapshot.status.place_id
    points, _ = snapshot.pointcloud.as_numpy()
    np.savez_compressed(directory / f"{stem}.npz", rgb=snapshot.image.data, points=points)
    snapshot.image.save(str(directory / f"{stem}.png"))
    return {
        "status": snapshot.status.model_dump(mode="json"),
        "evidence": [item.model_dump(mode="json") for item in snapshot.evidence],
        "arrays": f"{stem}.npz",
        "image": f"{stem}.png",
        "sha256": hashlib.sha256((directory / f"{stem}.npz").read_bytes()).hexdigest(),
        "point_count": len(points),
    }


def run_acceptance(
    directory: Path, *, blocked: bool, transport: TransportBackend = "zenoh"
) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=False)
    global_config.update(
        **dict(household_navigation_sim.global_config_overrides), viewer="none", transport=transport
    )
    coordinator = ModuleCoordinator()
    events: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "origin": "simulation",
        "localization": "mujoco_ground_truth",
        "clock_id": "unix",
        "blocked": blocked,
        "snapshots": [],
        "results": [],
    }
    scene_path = ALOHA_MINI2_NAV_MJCF.parent / (
        "household_navigation_blocked.xml" if blocked else "household_navigation.xml"
    )
    source_paths = [
        SPATIAL_SIM_CONFIG,
        SPATIAL_SIM_CONFIG.with_name("pilot.json"),
        ALOHA_MINI2_NAV_MJCF,
        scene_path,
        ALOHA_MINI2_NAV_MJCF.parent / "household_navigation.xml",
        Path(__file__),
        Path(__file__).with_name("spatial.py"),
        Path(__file__).with_name("spatial_module.py"),
    ]
    report["inputs"] = {
        str(path.relative_to(DIMOS_PROJECT_ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_paths
    }
    report["git_head"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=DIMOS_PROJECT_ROOT, text=True
    ).strip()
    report["versions"] = {name: version(name) for name in ("mujoco", "numpy")}
    report["transport"] = transport
    trajectory = (directory / "trajectory.jsonl").open("w")
    try:
        coordinator.start()
        sim_args: dict[str, Any] = {"headless": True}
        if blocked:
            sim_args["scene_xml"] = ALOHA_MINI2_NAV_MJCF.parent / "household_navigation_blocked.xml"
        coordinator.load_blueprint(
            household_navigation_sim.global_config(n_workers=0),
            {
                "alohamini2simmodule": sim_args,
                "householdspatialmodule": {"navigation_timeout_s": 15.0 if blocked else 90.0},
                "voxelgridmapper": {"block_count": 100000},
            },
        )
        spatial = cast("HouseholdSpatialModule", coordinator.get_instance(HouseholdSpatialModule))

        def sample() -> SpatialStatus:
            status = spatial.get_status()
            entry = status.model_dump(mode="json")
            trajectory.write(json.dumps(entry) + "\n")
            trajectory.flush()
            events.append(entry)
            return status

        def localized() -> bool:
            pose = sample().pose
            return pose is not None and 0 <= time.time() - pose.ts < 1.0

        wait_until(localized, timeout=45.0, message="no fresh localization")
        # Wait for mapping through the actual stream before issuing goals.
        planner = coordinator.get_instance(ReplanningAStarPlanner)
        costmap = planner.peek_stream("global_costmap", 30.0)
        if costmap is None:
            raise RuntimeError("no costmap generated from raycast pointclouds")
        report["initial_costmap_cells"] = int(costmap.grid.size)

        def finish() -> bool:
            return sample().state in {"arrived", "cancelled", "failed", "stop_unconfirmed"}

        for station in ("mesa_dormitorio",) if blocked else ("mesa_sala", "mesa_dormitorio"):
            spatial.go_to(station)
            wait_until(
                finish,
                timeout=100.0,
                interval=0.1,
                message=f"navigation never terminated: {station}",
            )
            result = sample()
            report["results"].append(result.model_dump(mode="json"))
            if blocked:
                assert result.state == "failed", result
                assert result.reason == "navigation_timeout_or_blocked", result
                break
            assert result.state == "arrived", result
            captured: list[SpatialSnapshot] = []

            def observe(place: str = station, snapshots: list[SpatialSnapshot] = captured) -> bool:
                snapshot = spatial.get_observation(place)
                if snapshot is not None:
                    snapshots.append(snapshot)
                return snapshot is not None

            wait_until(observe, timeout=15.0, message=f"no recent station observation: {station}")
            report["snapshots"].append(save_snapshot(captured[-1], directory))

        if not blocked:
            initial = sample().pose
            assert initial is not None
            spatial.go_to("mesa_sala")

            def moving() -> bool:
                status = sample()
                return (
                    status.state == "navigating"
                    and status.pose is not None
                    and np.hypot(status.pose.x - initial.x, status.pose.y - initial.y) > 0.15
                )

            wait_until(moving, timeout=30.0, message="return leg never moved before cancellation")
            report["cancel_requested_at"] = time.time()
            report["cancel_initial"] = spatial.cancel().model_dump(mode="json")
            wait_until(finish, timeout=8.0, interval=0.1)
            cancelled = sample()
            assert cancelled.state == "cancelled", cancelled
            report["results"].append(cancelled.model_dump(mode="json"))
            report["cancel_latency_s"] = cancelled.ts - report["cancel_requested_at"]
            stop_pose = cancelled.pose
            assert stop_pose is not None
            deadline = time.monotonic() + 1.0
            drift: list[float] = []

            def stays_stopped() -> bool:
                status = sample()
                assert status.pose is not None
                drift.append(
                    float(np.hypot(status.pose.x - stop_pose.x, status.pose.y - stop_pose.y))
                )
                return time.monotonic() >= deadline

            wait_until(stays_stopped, timeout=2.0, interval=0.1)
            report["post_cancel_drift_m"] = max(drift)
            assert max(drift) < 0.02, drift
        report["passed"] = True
    finally:
        trajectory.close()
        report["samples"] = len(events)
        (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        coordinator.stop()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=RECORDINGS_DIR / "household_f2" / str(time.time_ns())
    )
    parser.add_argument("--blocked", action="store_true")
    parser.add_argument("--transport", choices=("lcm", "zenoh"), default="zenoh")
    args = parser.parse_args()
    report = run_acceptance(args.output, blocked=args.blocked, transport=args.transport)
    print(json.dumps({"passed": report["passed"], "recording": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
