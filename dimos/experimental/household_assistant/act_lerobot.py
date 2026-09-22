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

"""F7 official LeRobot dataset/ACT APIs, imported only inside the LeRobot environment."""

import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import resource
import sys
import time
from typing import Any

from lerobot.configs import FeatureType, PolicyFeature
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.act.configuration_act import ACTConfig
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.act.processor_act import make_act_pre_post_processors
import numpy as np
import torch
from torch.utils.data import DataLoader

from dimos.experimental.household_assistant.act_contracts import (
    ACTProfile,
    MotorObservation,
    load_act_profile,
    synthetic_observation,
)


def features(profile: ACTProfile) -> dict[str, Any]:
    return {
        "observation.state": {
            "dtype": "float32",
            "shape": (len(profile.axes),),
            "names": list(profile.axes),
        },
        "action": {"dtype": "float32", "shape": (len(profile.axes),), "names": list(profile.axes)},
        "capture_times": {
            "dtype": "float64",
            "shape": (len(profile.cameras) + 2,),
            "names": ["joint_state", *profile.cameras, "issued_command"],
        },
        **{
            f"observation.images.{name}": {
                "dtype": "image",
                "shape": (*profile.image_hw, 3),
                "names": ["height", "width", "channel"],
            }
            for name in profile.cameras
        },
    }


class ACTRecorder:
    """One official LeRobot dataset; additional provenance lives beside its metadata."""

    def __init__(self, root: Path, profile: ACTProfile) -> None:
        self.profile = profile
        self.root = root
        self.dataset = LeRobotDataset.create(
            "local/" + profile.executor_id,
            root=root,
            fps=profile.fps,
            robot_type="alohamini1_artificial_unbound",
            features=features(profile),
            use_videos=False,
        )
        self.episodes: list[dict[str, Any]] = []
        self._frames = 0
        self._last_at: float | None = None
        self._sessions: dict[str, str] = {}

    def add(
        self, observation: MotorObservation, issued_action: np.ndarray, *, issued_at: float
    ) -> None:
        observation.validate(self.profile, now=issued_at)
        if issued_action.shape != observation.state.shape or not np.isfinite(issued_action).all():
            raise ValueError("recorded command dimensions/nonfinite values")
        if np.any(issued_action < self.profile.lower) or np.any(issued_action > self.profile.upper):
            raise ValueError("recorded action outside profile")
        if np.any(np.abs(issued_action - observation.state) > self.profile.max_step):
            raise ValueError("recorded command exceeds allowed step")
        if (
            self._last_at is not None
            and abs(issued_at - self._last_at - 1 / self.profile.fps) > 0.02
        ):
            raise ValueError("capture gap/jitter: reject episode instead of filling missing frames")
        self.dataset.add_frame(
            {
                "observation.state": observation.state.copy(),
                "action": issued_action.astype(np.float32),
                "capture_times": np.array(
                    [
                        observation.captured_at,
                        *[observation.camera_times[n] for n in self.profile.cameras],
                        issued_at,
                    ],
                    dtype=np.float64,
                ),
                **{
                    f"observation.images.{name}": image
                    for name, image in observation.images.items()
                },
                "task": self.profile.skill_id,
            }
        )
        self._frames += 1
        self._last_at = issued_at

    def save_episode(self, *, session_id: str, split: str, reset_id: str) -> None:
        if split not in {"train", "validation", "test"} or not session_id or not reset_id:
            raise ValueError("session, reset and split are required")
        if session_id in self._sessions and self._sessions[session_id] != split:
            raise ValueError("session leakage across dataset splits")
        if self._frames < self.profile.chunk_size:
            raise ValueError("episode shorter than an action chunk")
        self.dataset.save_episode()
        self._sessions[session_id] = split
        self.episodes.append(
            {
                "episode_index": len(self.episodes),
                "session_id": session_id,
                "split": split,
                "reset_id": reset_id,
                "frames": self._frames,
                "provenance": self.profile.provenance,
            }
        )
        self._frames, self._last_at = 0, None
        self._write_manifest()

    def _write_manifest(self) -> None:
        (self.root / "meta/household.json").write_text(
            json.dumps(
                {
                    "profile": self.profile.model_dump(),
                    "profile_sha256": self.profile.fingerprint(),
                    "episodes": self.episodes,
                },
                indent=2,
            )
            + "\n"
        )

    def discard_episode(self) -> None:
        self.dataset.clear_episode_buffer()
        self._frames, self._last_at = 0, None

    def close(self) -> None:
        if self._frames:
            self.discard_episode()
        self.dataset.finalize()  # type: ignore[no-untyped-call]  # Upstream API lacks annotation.
        self._write_manifest()


def create_artificial(root: Path, profile: ACTProfile) -> None:
    recorder = ACTRecorder(root, profile)
    try:
        for episode in range(6):
            for frame in range(12):
                at = 1000.0 + episode * 10 + frame / profile.fps
                observation = synthetic_observation(profile, frame, episode, at=at)
                command = observation.state + np.float32(0.01)
                recorder.add(observation, command, issued_at=at)
            split = ("train", "validation", "test")[episode // 2]
            recorder.save_episode(
                session_id="synthetic_" + split, split=split, reset_id=f"reset_{episode}"
            )
    finally:
        recorder.close()


def read_frame(dataset: LeRobotDataset, index: int) -> dict[str, Any]:
    frame = dataset[index]
    if not isinstance(frame, dict):
        raise ValueError("expected one dataset frame")
    return frame


def train_stats(dataset: LeRobotDataset, profile: ACTProfile) -> dict[str, Any]:
    # Only training sessions contribute normalization; never use global meta.stats.
    result = {}
    for key in [
        "observation.state",
        "action",
        *[f"observation.images.{n}" for n in profile.cameras],
    ]:
        values = torch.stack([read_frame(dataset, i)[key] for i in range(len(dataset))]).float()
        dims = (0, 2, 3) if "images" in key else (0,)
        mean, std = values.mean(dim=dims), values.std(dim=dims, unbiased=False).clamp_min(1e-6)
        if "images" in key:
            mean, std = mean[:, None, None], std[:, None, None]
        result[key] = {"mean": mean.tolist(), "std": std.tolist()}
    return result


def train(
    root: Path, output: Path, profile: ACTProfile, *, steps: int, device: str
) -> dict[str, Any]:
    torch.manual_seed(7)
    torch.set_num_threads(2)
    if steps < 1:
        raise ValueError("at least one optimization step is required")
    manifest = json.loads((root / "meta/household.json").read_text())
    if manifest["profile_sha256"] != profile.fingerprint():
        raise ValueError("dataset/profile mismatch")
    splits = {
        name: [e["episode_index"] for e in manifest["episodes"] if e["split"] == name]
        for name in ("train", "validation", "test")
    }
    if any(not values for values in splits.values()):
        raise ValueError("all session splits are required")
    repo = "local/" + profile.executor_id
    stats_data = LeRobotDataset(repo, root=root, episodes=splits["train"])
    stats = train_stats(stats_data, profile)
    config = ACTConfig(
        device=device,
        input_features={
            "observation.state": PolicyFeature(type=FeatureType.STATE, shape=(len(profile.axes),)),
            **{
                f"observation.images.{name}": PolicyFeature(
                    type=FeatureType.VISUAL, shape=(3, *profile.image_hw)
                )
                for name in profile.cameras
            },
        },
        output_features={
            "action": PolicyFeature(type=FeatureType.ACTION, shape=(len(profile.axes),))
        },
        chunk_size=profile.chunk_size,
        n_action_steps=profile.execute_steps,
        pretrained_backbone_weights=None,
        dim_model=64,
        n_heads=4,
        dim_feedforward=128,
        n_encoder_layers=1,
        n_decoder_layers=1,
        n_vae_encoder_layers=1,
        latent_dim=8,
        push_to_hub=False,
    )
    data = LeRobotDataset(
        repo,
        root=root,
        episodes=splits["train"],
        delta_timestamps={"action": [i / profile.fps for i in range(profile.chunk_size)]},
    )
    validation = LeRobotDataset(
        repo,
        root=root,
        episodes=splits["validation"],
        delta_timestamps={"action": [i / profile.fps for i in range(profile.chunk_size)]},
    )
    policy = ACTPolicy(config).to(device)
    pre, post = make_act_pre_post_processors(config, stats)
    optimizer = torch.optim.AdamW(policy.parameters(), lr=1e-4)
    loader = DataLoader(data, batch_size=2, shuffle=False, num_workers=0)
    iterator = iter(loader)
    started = time.monotonic()
    losses = []
    policy.train()
    for _ in range(steps):
        try:
            batch = next(iterator)
        except StopIteration:
            iterator = iter(loader)
            batch = next(iterator)
        loss, _ = policy(pre(batch))
        if not torch.isfinite(loss):
            raise ValueError("nonfinite training loss")
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(policy.parameters(), 1.0)
        optimizer.step()
        losses.append(float(loss.detach()))
    policy.eval()
    with torch.no_grad():
        val_loss, _ = policy(pre(next(iter(DataLoader(validation, batch_size=2)))))
        normalized = policy.predict_action_chunk(pre(read_frame(data, 0)))
        action = post(normalized[0]).detach().cpu()
    output.mkdir(parents=True, exist_ok=False)
    policy.save_pretrained(output)
    pre.save_pretrained(output, config_filename="preprocessor.json")
    post.save_pretrained(output, config_filename="postprocessor.json")
    (output / "household_profile.json").write_text(profile.model_dump_json(indent=2) + "\n")
    (output / "training_stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    report = {
        "provenance": profile.provenance,
        "device": device,
        "steps": steps,
        "losses": losses,
        "validation_loss": float(val_loss),
        "elapsed_s": time.monotonic() - started,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "parameters": sum(p.numel() for p in policy.parameters()),
        "action_shape": list(action.shape),
        "finite_inference": bool(torch.isfinite(action).all()),
        "dataset_frames": data.meta.total_frames,
        "episodes": manifest["episodes"],
        "normalization_sessions": sorted(
            {e["session_id"] for e in manifest["episodes"] if e["split"] == "train"}
        ),
        "heldout_test_used": False,
        "profile_sha256": profile.fingerprint(),
        "physical_skill_trained": False,
    }
    (output / "smoke_report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def serve(checkpoint: Path, profile: ACTProfile, device: str) -> None:
    saved = load_act_profile(checkpoint / "household_profile.json")
    if saved != profile:
        raise ValueError("checkpoint profile mismatch")
    torch.set_num_threads(2)
    with redirect_stdout(sys.stderr):
        policy = (
            ACTPolicy.from_pretrained(checkpoint, local_files_only=True, strict=True)
            .to(device)
            .eval()
        )
        expected_inputs = {
            "observation.state": PolicyFeature(type=FeatureType.STATE, shape=(len(profile.axes),)),
            **{
                f"observation.images.{name}": PolicyFeature(
                    type=FeatureType.VISUAL, shape=(3, *profile.image_hw)
                )
                for name in profile.cameras
            },
        }
        if (
            policy.config.input_features != expected_inputs
            or policy.config.output_features
            != {"action": PolicyFeature(type=FeatureType.ACTION, shape=(len(profile.axes),))}
            or policy.config.chunk_size != profile.chunk_size
            or policy.config.n_action_steps != profile.execute_steps
        ):
            raise ValueError("checkpoint dimensions/cameras/chunk mismatch")
        policy.config.device = device
        stats = json.loads((checkpoint / "training_stats.json").read_text())
        pre, post = make_act_pre_post_processors(policy.config, stats)
    print(json.dumps({"ready": True, "profile_sha256": profile.fingerprint()}), flush=True)
    for line in sys.stdin:
        payload = json.loads(line)
        if payload.get("close"):
            return
        started = time.monotonic()
        with torch.inference_mode(), redirect_stdout(sys.stderr):
            batch = {"observation.state": torch.tensor(payload["state"], dtype=torch.float32)}
            for name in profile.cameras:
                image = np.asarray(payload["images"][name], dtype=np.uint8)
                if image.shape != (*profile.image_hw, 3):
                    raise ValueError("image shape mismatch")
                batch[f"observation.images.{name}"] = (
                    torch.from_numpy(image.copy()).permute(2, 0, 1).float() / 255
                )
            chunk = post(policy.predict_action_chunk(pre(batch))[0]).cpu()
        print(
            json.dumps({"actions": chunk.tolist(), "elapsed_s": time.monotonic() - started}),
            flush=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["smoke", "serve"])
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=5)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    profile = load_act_profile(args.profile)
    if args.mode == "serve":
        serve(args.output, profile, args.device)
    else:
        args.output.mkdir(parents=True, exist_ok=False)
        create_artificial(args.output / "dataset", profile)
        print(
            json.dumps(
                train(
                    args.output / "dataset",
                    args.output / "checkpoint",
                    profile,
                    steps=args.steps,
                    device=args.device,
                )
            )
        )


if __name__ == "__main__":
    main()
