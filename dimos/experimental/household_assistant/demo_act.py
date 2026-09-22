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

"""F7 checkpoint → DimOS/F4 command → dry-run receiver, with no actuator access."""

import argparse
import json
from pathlib import Path
import threading
import time
from typing import Any

from dimos.experimental.household_assistant.act_adapter import ACTDryRunAdapter, DryRunReceiver
from dimos.experimental.household_assistant.act_contracts import synthetic_observation
from dimos.experimental.household_assistant.act_process import LeRobotProcess
from dimos.experimental.household_assistant.contracts import ActionProposal
from dimos.experimental.household_assistant.mission_contracts import ExecutorCommand


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.output.mkdir(parents=True, exist_ok=False)
    policy = LeRobotProcess(
        python=args.python,
        source=args.lerobot_source,
        deps=args.deps,
        profile_path=args.profile,
        checkpoint=args.checkpoint,
        log=args.output / "worker.log",
        device=args.device,
    )
    receiver = DryRunReceiver()
    adapter = ACTDryRunAdapter(policy, receiver)
    wait = threading.Event()
    profile = policy.profile
    at = time.time()
    observation = synthetic_observation(profile, 0, 0, at=at)
    command = ExecutorCommand(
        kind="start",
        executor_id=profile.executor_id,
        action=ActionProposal(
            id="f7_action",
            request_id="f7_request",
            skill_id=profile.skill_id,
            destination_id="mesa_sala",
            arm="right",
            object_id="bottle_01",
        ),
        issued_at=at,
        clock_id="unix",
    )
    try:
        adapter.accept(command, observation, now=at)
        deadline = time.monotonic() + 15
        while len(receiver.commands) < profile.execute_steps and time.monotonic() < deadline:
            now = time.time()
            adapter.tick(synthetic_observation(profile, 0, 0, at=now), now=now)
            if adapter.results[-1].stage == "failed":
                raise RuntimeError(adapter.results[-1].detail)
            wait.wait(0.01)
        if len(receiver.commands) != profile.execute_steps:
            raise RuntimeError("no ACT commands received before deadline")
        # Start another inference then cancel. Its completion cannot dispatch actions.
        adapter.tick(synthetic_observation(profile, 0, 0, at=time.time()), now=time.time())
        count = len(receiver.commands)
        started = time.monotonic()
        adapter.accept(command.model_copy(update={"kind": "stop"}), observation, now=time.time())
        cancel_s = time.monotonic() - started
        adapter.tick(synthetic_observation(profile, 0, 0, at=time.time()), now=time.time())
        assert len(receiver.commands) == count and receiver.stopped
        report = {
            "result": "passed",
            "profile_sha256": profile.fingerprint(),
            "provenance": profile.provenance,
            "physical_actuators": False,
            "commands_sent": count,
            "action_dimensions": len(receiver.commands[0][2]),
            "intervals_s": [
                b[1] - a[1] for a, b in zip(receiver.commands, receiver.commands[1:], strict=False)
            ],
            "inference_latency_s": list(policy.latencies),
            "cancel_s": cancel_s,
            "results": [r.model_dump(mode="json") for r in adapter.results],
        }
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        return report
    finally:
        adapter.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--lerobot-source", type=Path, required=True)
    parser.add_argument("--deps", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    print(json.dumps(run(parser.parse_args())))


if __name__ == "__main__":
    main()
