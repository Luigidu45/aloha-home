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

"""Thread-safe handoff for perception snapshots, without freshening old sensor timestamps."""

from threading import Lock

from dimos.experimental.domestic_assistance.contracts import Observation, Origin


class ObservationBuffer:
    """Sensor adapters publish complete snapshots; the runner enforces freshness on read.

    Publishing is not sensor fusion: producers remain responsible for calibrations,
    clock synchronization and deriving facts from evidence available on the real robot.
    """

    def __init__(self, origin: Origin) -> None:
        self._origin = origin
        self._latest: Observation | None = None
        self._lock = Lock()

    def publish(self, observation: Observation) -> None:
        if observation.origin != self._origin:
            raise ValueError("observation origin mismatch")
        with self._lock:
            if self._latest is not None and observation.captured_at <= self._latest.captured_at:
                raise ValueError("snapshot must be newer than the previous observation")
            self._latest = observation

    def observe(self) -> Observation:
        with self._lock:
            if self._latest is None:
                raise ValueError("no sensor observation has been received")
            return self._latest

    def observe_after(self, captured_at: float) -> Observation | None:
        """Return a newer snapshot without relabeling an old snapshot as fresh."""
        with self._lock:
            if self._latest is None or self._latest.captured_at <= captured_at:
                return None
            return self._latest
