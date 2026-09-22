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

"""LeRobot subprocess bridge; keep its Torch environment separate from DimOS."""

import json
import os
from pathlib import Path
import select
import subprocess
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dimos.experimental.household_assistant.act_contracts import (
    MotorObservation,
    load_act_profile,
    validate_chunk,
)


class LeRobotProcess:
    def __init__(
        self,
        *,
        python: Path,
        source: Path,
        deps: Path,
        profile_path: Path,
        checkpoint: Path,
        log: Path,
        device: str = "cpu",
    ) -> None:
        self.profile = load_act_profile(profile_path)
        if load_act_profile(checkpoint / "household_profile.json") != self.profile:
            raise ValueError("checkpoint/profile mismatch")
        root = Path(__file__).resolve().parents[3]
        env = dict(os.environ)
        env.update(
            PYTHONPATH=os.pathsep.join(map(str, [deps.resolve(), source.resolve(), root])),
            HF_HUB_OFFLINE="1",
            HF_DATASETS_OFFLINE="1",
        )
        self.latencies: list[float] = []
        self._log = log.open("w")
        self._process = subprocess.Popen(
            [
                str(python),
                "-m",
                "dimos.experimental.household_assistant.act_lerobot",
                "serve",
                "--profile",
                str(profile_path.resolve()),
                "--output",
                str(checkpoint.resolve()),
                "--device",
                device,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._log,
            text=True,
            bufsize=1,
            env=env,
            cwd=root,
        )
        try:
            reply = self._read(120)
            if reply != {"ready": True, "profile_sha256": self.profile.fingerprint()}:
                raise RuntimeError("unexpected ACT startup receipt")
        except BaseException:
            self.close()
            raise

    def _read(self, timeout: float) -> dict[str, Any]:
        assert self._process.stdout is not None
        if not select.select([self._process.stdout], [], [], timeout)[0]:
            raise TimeoutError("ACT subprocess deadline")
        line = self._process.stdout.readline()
        if not line:
            raise RuntimeError("ACT subprocess exited; inspect worker log")
        result: dict[str, Any] = json.loads(line)
        return result

    def predict(self, observation: MotorObservation) -> NDArray[np.float32]:
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(observation.payload()) + "\n")
        self._process.stdin.flush()
        result = self._read(self.profile.inference_timeout_s)
        actions = np.asarray(result["actions"], dtype=np.float32)
        validate_chunk(self.profile, actions)
        self.latencies.append(float(result["elapsed_s"]))
        return actions

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
        for stream in (self._process.stdin, self._process.stdout):
            if stream:
                stream.close()
        self._log.close()
