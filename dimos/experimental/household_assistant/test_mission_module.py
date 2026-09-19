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

"""Cancellation remains available while a spatial adapter call is blocked."""

import threading

import pytest

from dimos.experimental.household_assistant.mission import MissionManager
from dimos.experimental.household_assistant.mission_module import ExecutorMailbox
from dimos.experimental.household_assistant.mission_sequence import MissionSequence
from dimos.experimental.household_assistant.mission_simulation import (
    ArtificialMissionExecutor,
    simulation_bindings,
)
from dimos.experimental.household_assistant.spatial import SpatialStatus


@pytest.fixture
def blocked_adapter(pilot, request_a, mocker):
    manager = MissionManager(pilot, simulation_bindings(pilot), stop_timeout_s=1)
    seed = ArtificialMissionExecutor(manager)
    first = seed.step(now=100)
    manager.submit(request_a, now=100)
    MissionSequence(manager, request_a).advance(first, now=100)
    mailbox = ExecutorMailbox(pilot, "right")
    mailbox.enqueue(manager.take_commands())
    entered = threading.Event()
    release = threading.Event()

    def blocked_read():
        entered.set()
        release.wait(5)
        return SpatialStatus(ts=101)

    spatial = mocker.Mock()
    spatial.get_status.side_effect = blocked_read
    adapter = ArtificialMissionExecutor(mailbox, spatial=spatial)
    worker = threading.Thread(target=adapter.step, kwargs={"now": 101})
    worker.start()
    try:
        yield manager, mailbox, entered, release, spatial
    finally:
        release.set()
        worker.join(timeout=2)


@pytest.mark.timeout(5)
def test_cancel_and_watchdog_do_not_wait_for_blocked_adapter(blocked_adapter):
    manager, mailbox, entered, release, spatial = blocked_adapter
    assert entered.wait(1)
    manager.cancel(now=101)
    mailbox.enqueue(manager.take_commands())
    assert manager.snapshot().state == "stopping"
    assert not release.is_set()
    manager.tick(now=103)
    assert manager.snapshot().state == "stop_unconfirmed"
    commands = mailbox.take_commands()
    assert [c.kind for c in commands] == ["stop"]
    spatial.go_to.assert_not_called()


def test_adapter_failure_requests_stop_without_publishing_more_starts(pilot, request_a):
    manager = MissionManager(pilot, simulation_bindings(pilot))
    driver = ArtificialMissionExecutor(manager)
    first = driver.step(now=100)
    manager.submit(request_a, now=100)
    MissionSequence(manager, request_a).advance(first, now=100)
    manager.fail("adapter_exception", now=100.1)
    assert [c.kind for c in manager.take_commands()] == ["stop"]
    assert manager.snapshot().state == "stopping"
    assert manager.events()[-1].detail == "adapter_exception"
