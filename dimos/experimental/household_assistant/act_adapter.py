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

"""Cancellable F4 command adapter with an explicitly actuator-free receiver."""

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
import threading
import time
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from dimos.experimental.household_assistant.act_contracts import (
    ACTProfile,
    MotorObservation,
    validate_chunk,
)
from dimos.experimental.household_assistant.mission_contracts import ExecutorCommand, ExecutorResult


class ChunkPolicy(Protocol):
    profile: ACTProfile

    def predict(self, observation: MotorObservation) -> NDArray[np.float32]: ...
    def close(self) -> None: ...


class DryRunReceiver:
    """Stores commands only; no motor transport exists in this receiver."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, float, NDArray[np.float32]]] = []
        self.stopped = True

    def send(self, action_id: str, action: NDArray[np.float32], now: float) -> None:
        self.commands.append((action_id, now, action.copy()))
        self.stopped = False

    def stop(self) -> bool:
        self.stopped = True
        return True


class ACTDryRunAdapter:
    """One in-flight chunk. Cancellation never waits on model inference.

    F7 deliberately has no physical receiver or blueprint binding. A finished
    motion still needs F4's independent task postcondition verification.
    """

    def __init__(self, policy: ChunkPolicy, receiver: DryRunReceiver) -> None:
        if type(receiver) is not DryRunReceiver:
            raise ValueError("F7 supports only the actuator-free receiver")
        self.profile = policy.profile
        self.policy, self.receiver = policy, receiver
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="act-inference")
        self._future: Future[NDArray[np.float32]] | None = None
        self._future_generation = 0
        self._generation = 0
        self._source_at = 0.0
        self._started_mono = 0.0
        self._queue: deque[NDArray[np.float32]] = deque()
        self._command: ExecutorCommand | None = None
        self._last_send = float("-inf")
        self._seen: set[str] = set()
        self.results: list[ExecutorResult] = []
        self._closed = False

    def _result(self, stage: str, now: float, detail: str) -> None:
        if self._command:
            self.results.append(
                ExecutorResult.model_validate(
                    {
                        "executor_id": self.profile.executor_id,
                        "action_id": self._command.action.id,
                        "stage": stage,
                        "recorded_at": now,
                        "clock_id": self.profile.clock_id,
                        "detail": detail,
                    }
                )
            )

    def accept(
        self, command: ExecutorCommand, observation: MotorObservation, *, now: float
    ) -> None:
        with self._lock:
            if (
                command.executor_id != self.profile.executor_id
                or command.clock_id != self.profile.clock_id
            ):
                raise ValueError("executor/clock mismatch")
            if command.kind == "stop":
                if self._command is None or self._command.action.id != command.action.id:
                    raise ValueError("stop action mismatch")
                self.cancel(now=now)
                return
            if (
                self._closed
                or self._command is not None
                or (self._future and not self._future.done())
            ):
                raise RuntimeError("adapter unavailable/busy")
            if command.action.id in self._seen:
                raise ValueError("action replay rejected")
            if (
                command.action.skill_id != self.profile.skill_id
                or command.action.arm != self.profile.arm
            ):
                raise ValueError("policy skill/arm mismatch")
            observation.validate(self.profile, now=now)
            self._generation += 1
            self._command = command
            self._seen.add(command.action.id)
            self._last_send = float("-inf")
            self._queue.clear()
            self._result("running", now, "dry_run_only_no_actuators")

    def cancel(self, *, now: float) -> None:
        with self._lock:
            self._generation += 1
            self._queue.clear()
            if self.receiver.stop():
                self._result("stopped", now, "dry_run_receiver_stopped_queue_cleared")
            self._command = None

    def _fail(self, now: float, detail: str) -> None:
        self._queue.clear()
        self._generation += 1
        self.receiver.stop()
        self._result("failed", now, detail)
        self._command = None

    def tick(self, observation: MotorObservation, *, now: float) -> None:
        with self._lock:
            if self._closed or self._command is None:
                return
            try:
                observation.validate(self.profile, now=now)
                if self._future:
                    if not self._future.done():
                        if time.monotonic() - self._started_mono > self.profile.inference_timeout_s:
                            raise ValueError("inference timeout")
                        return
                    completed = self._future
                    self._future = None
                    if self._future_generation != self._generation:
                        return
                    chunk = completed.result()
                    validate_chunk(self.profile, chunk)
                    self._queue.extend(chunk[: self.profile.execute_steps].copy())
                if self._queue:
                    if not 0 <= now - self._source_at <= self.profile.prediction_ttl_s:
                        raise ValueError("prediction expired")
                    if now < self._last_send:
                        raise ValueError("clock moved backwards")
                    if now - self._last_send + 1e-9 < 1 / self.profile.fps:
                        return
                    action = self._queue[0]
                    if np.any(np.abs(action - observation.state) > self.profile.max_step):
                        raise ValueError("action step exceeds bound")
                    # Check and send share the same lock as cancellation.
                    self.receiver.send(self._command.action.id, action, now)
                    self._queue.popleft()
                    self._last_send = now
                else:
                    # Own immutable copies: camera producers may recycle their arrays.
                    snapshot = MotorObservation(
                        state=observation.state.copy(),
                        images={k: v.copy() for k, v in observation.images.items()},
                        captured_at=observation.captured_at,
                        camera_times=dict(observation.camera_times),
                        axes=observation.axes,
                    )
                    self._source_at = observation.captured_at
                    self._future_generation = self._generation
                    self._started_mono = time.monotonic()
                    self._future = self._pool.submit(self.policy.predict, snapshot)
            except Exception as exc:
                self._fail(now, str(exc))

    def finish_motion(self, *, now: float) -> None:
        """Explicit trajectory-end signal, never a declaration that the object was grasped."""
        with self._lock:
            if self._command is None or self._queue or self._future is not None:
                raise RuntimeError("motion is not ready to finish")
            self.receiver.stop()
            self._result("finished", now, "motion_only_requires_independent_F4_verification")
            self._command = None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.cancel(now=time.time())
        self.policy.close()
        self._pool.shutdown(wait=True, cancel_futures=True)
