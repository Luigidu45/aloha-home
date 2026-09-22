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

"""F6 command boundaries use the real mission manager and artificial executor."""

from fastapi.testclient import TestClient
import pytest

from dimos.experimental.household_assistant.contracts import MissionRequest, Predicate
from dimos.experimental.household_assistant.mission import MissionManager
from dimos.experimental.household_assistant.mission_sequence import MissionSequence
from dimos.experimental.household_assistant.mission_simulation import (
    ArtificialMissionExecutor,
    simulation_bindings,
)
from dimos.experimental.household_assistant.spatial import PoseSample, SpatialStatus
from dimos.experimental.household_assistant.web_runtime import SessionMissionPort
from dimos.experimental.household_assistant.web_session import AssistanceSession, WebCommand
from dimos.web.household_server import HouseholdWebServer


@pytest.fixture
def web(pilot, tmp_path, mocker):
    now = [100.0]
    manager = MissionManager(pilot, simulation_bindings(pilot), clock_id="test")
    driver = ArtificialMissionExecutor(manager)
    driver.step(now=now[0])
    module = mocker.Mock()
    module.get_planning_state.side_effect = manager.planning_state
    module.submit_request.side_effect = lambda raw: manager.submit(
        MissionRequest.model_validate_json(raw), now=now[0]
    )
    module.clarify_mission.side_effect = lambda answer, rev: manager.clarify(
        answer, expected_revision=rev, now=now[0]
    )
    module.cancel_mission.side_effect = lambda pause=False: manager.cancel(pause=pause, now=now[0])
    module.resume_mission.side_effect = lambda: manager.resume(now=now[0])
    module.choose_target.side_effect = lambda obj, rev: manager.select_target(
        obj, expected_revision=rev, now=now[0]
    )
    module.redirect_mission.side_effect = lambda dst, rev: manager.redirect(
        dst, expected_revision=rev, now=now[0]
    )
    session = AssistanceSession(
        module, mode="fixture", log_path=tmp_path / "interaction.jsonl", clock=lambda: now[0]
    )
    return session, manager, driver, now


def send(session, kind, **kwargs):
    command = WebCommand(
        id=f"command_{session.version:04d}",
        session=session.id,
        version=session.version,
        kind=kind,
        **kwargs,
    )
    return command, session.command(command)


def start_request(session):
    send(session, "draft", instruction="Lleva la botella al dormitorio")
    return send(session, "confirm")


def test_double_submit_returns_same_receipt_without_second_mission(web):
    session, manager, _, _ = web
    command, receipt = start_request(session)
    assert session.command(command) == receipt
    assert len([e for e in manager.events() if e.kind == "request"]) == 1
    with pytest.raises(ValueError, match="Identificador"):
        session.command(command.model_copy(update={"destination": "mesa_sala"}))


def test_incomplete_request_keeps_context_and_requires_corrected_confirmation(web):
    session, manager, _, _ = web
    send(session, "draft", instruction="Tráeme algo")
    assert session.state()["draft"]["ready"] is False
    with pytest.raises(ValueError, match="Primero revisa"):
        send(session, "confirm")
    send(session, "answer", instruction="Quiero la botella pequeña")
    assert session.state()["draft"]["ready"] is True
    assert [x["text"] for x in session.history if x["role"] == "user"] == [
        "Tráeme algo",
        "Quiero la botella pequeña",
    ]
    assert manager.snapshot().state == "idle"
    send(session, "confirm")
    assert manager.snapshot().state == "preparing"


def test_stale_form_and_previous_server_commands_never_start_mission(web):
    session, manager, _, _ = web
    send(session, "draft", instruction="Lleva la botella")
    for change in ({"version": 0}, {"session": "old_server"}):
        c = WebCommand(
            id="old_command", session=session.id, version=session.version, kind="confirm"
        ).model_copy(update=change)
        with pytest.raises(ValueError):
            session.command(c)
    assert manager.snapshot().state == "idle"


def test_cancel_is_available_with_stale_form_and_waits_for_stop_evidence(web):
    session, manager, driver, now = web
    start_request(session)
    c = WebCommand(id="cancel_0001", session=session.id, version=0, kind="cancel")
    session.command(c)
    assert session.state()["mission"]["state"] == "stopping"
    now[0] += 0.2
    driver.step(now=now[0])
    assert session.state()["mission"]["state"] == "cancelled"
    assert session.enabled is False


def test_destination_change_requires_confirmed_pause_and_fresh_confirmation(web):
    session, manager, driver, now = web
    start_request(session)
    send(session, "redirect", destination="mesa_sala")
    assert manager.snapshot().state == "stopping"
    with pytest.raises(RuntimeError, match="confirmed pause"):
        send(session, "confirm_redirect", revision=manager.snapshot().revision)
    now[0] += 0.2
    driver.step(now=now[0])
    assert manager.snapshot().state == "paused"
    send(session, "confirm_redirect", revision=manager.snapshot().revision)
    assert manager.planning_state().request.destination_id == "mesa_sala"
    assert manager.snapshot().state == "preparing"
    assert session.redirect_to is None


def test_old_object_choice_rejected_after_scene_changes(web):
    session, manager, driver, now = web
    start_request(session)
    driver.place = "mesa_sala"
    driver.scenario = "ambiguous"
    now[0] += 0.1
    driver.step(now=now[0])
    manager.ask("choose a bottle", now=now[0])
    old = manager.snapshot().revision
    assert len(session.state()["candidates"]) == 2
    driver.scenario = "absent"
    now[0] += 0.1
    driver.step(now=now[0])
    with pytest.raises(ValueError, match="scene changed"):
        send(session, "select", object_id="bottle_01", revision=old)
    assert manager.snapshot().selected_object_id is None
    now[0] += 3
    assert session.state()["candidates"] == []
    assert session.state()["world_fresh"] is False


def test_loaded_redirect_preserves_payload_and_verifies_delivery_at_new_destination(web):
    session, manager, driver, now = web
    start_request(session)
    sequence = MissionSequence(manager, manager.planning_state().request)
    for _ in range(100):
        now[0] += 0.1
        frame = driver.step(now=now[0])
        if manager.snapshot().held_object_id:
            break
        sequence.advance(frame, now=now[0])
    assert manager.snapshot().held_object_id == "bottle_01"
    send(session, "redirect", destination="mesa_sala")
    now[0] += 0.2
    driver.step(now=now[0])
    send(session, "confirm_redirect", revision=manager.snapshot().revision)
    sequence.request = manager.planning_state().request
    assert manager.snapshot().held_object_id == "bottle_01"
    for _ in range(100):
        now[0] += 0.1
        frame = driver.step(now=now[0])
        sequence.advance(frame, now=now[0])
        if manager.snapshot().state == "succeeded":
            break
    assert manager.snapshot().state == "succeeded"
    assert driver.placed_at == "mesa_sala"


def test_http_session_header_and_command_replay(web, tmp_path):
    session, manager, _, _ = web
    (tmp_path / "index.html").write_text('<div id="root"></div>')
    (tmp_path / "assets").mkdir()
    server = HouseholdWebServer(session, tmp_path, host="127.0.0.1", port=0)
    try:
        with TestClient(server.app) as client:
            assert client.get("/").url.path == "/assistance"
            state = client.get("/api/assistance/state").json()
            c = WebCommand(
                id="request_test",
                session=state["session"],
                version=0,
                kind="draft",
                instruction="Lleva la botella",
            )
            assert client.post("/api/assistance/command", json=c.model_dump()).status_code == 403
            headers = {"X-Dimos-Session": session.id}
            first = client.post("/api/assistance/command", json=c.model_dump(), headers=headers)
            assert first.status_code == 200
            assert (
                client.post("/api/assistance/command", json=c.model_dump(), headers=headers).json()
                == first.json()
            )
            assert manager.snapshot().state == "idle"
    finally:
        server.dispose_all()


def test_free_text_clarification_keeps_mission_without_inventing_a_target(web):
    session, manager, _, now = web
    start_request(session)
    original = manager.planning_state().request
    manager.ask("Where is the bottle?", now=now[0])
    send(
        session,
        "answer",
        instruction="Está en la mesa de la sala",
        revision=manager.snapshot().revision,
    )
    revised = manager.planning_state().request
    assert revised.id == original.id
    assert revised.destination_id == original.destination_id
    assert revised.instruction.startswith(original.instruction)
    assert "Está en la mesa" in revised.instruction
    assert manager.snapshot().selected_object_id is None
    assert manager.snapshot().state == "preparing"


def test_late_vlm_cannot_admit_after_http_cancel(web, pilot):
    session, manager, _, _ = web
    start_request(session)
    port = SessionMissionPort(session, session.module, pilot, session.generation)
    expected = manager.snapshot()
    send(session, "cancel")
    with pytest.raises(ValueError, match="operator changed"):
        port.admit_planner(
            expected=expected,
            request=None,
            action=None,
            question="Late question",
            target=None,
            now=100,
        )
    assert manager.snapshot().state == "stopping"
    session.module.admit_planner_json.assert_not_called()


@pytest.mark.parametrize("navigation_state", ["navigating", "cancelled"])
def test_leaving_station_invalidates_previous_base_region(pilot, mocker, navigation_state):
    manager = MissionManager(pilot, simulation_bindings(pilot), clock_id="unix")
    spatial = mocker.Mock()
    pose = PoseSample(ts=100, x=-2.5, y=0.5, yaw=1.57, frame_id="world")
    spatial.get_status.return_value = SpatialStatus(
        ts=100, state="arrived", place_id="mesa_sala", pose=pose
    )
    driver = ArtificialMissionExecutor(manager, spatial=spatial)
    at_source = driver.step(now=100)
    assert any(
        o.key.subject_id == "base" and o.key.predicate == Predicate.AT and o.value is True
        for o in at_source.observations
    )
    spatial.get_status.return_value = SpatialStatus(
        ts=101,
        state=navigation_state,
        place_id="mesa_dormitorio",
        pose=pose.model_copy(update={"ts": 101, "x": -1.0}),
    )
    en_route = driver.step(now=101)
    assert not any(
        o.key.subject_id == "base" and o.key.predicate == Predicate.AT and o.value is True
        for o in en_route.observations
    )


def test_redirect_between_stations_navigates_back_instead_of_placing_there(web):
    session, manager, driver, now = web
    start_request(session)
    sequence = MissionSequence(manager, manager.planning_state().request)
    for _ in range(100):
        now[0] += 0.1
        frame = driver.step(now=now[0])
        if "prepare_transport" in manager.snapshot().completed_actions:
            break
        sequence.advance(frame, now=now[0])
    assert manager.snapshot().held_object_id == "bottle_01"
    assert driver.loaded
    driver.place = "between_stations"
    send(session, "redirect", destination="mesa_sala")
    now[0] += 0.2
    frame = driver.step(now=now[0])
    assert manager.snapshot().state == "paused"
    send(session, "confirm_redirect", revision=manager.snapshot().revision)
    sequence.request = manager.planning_state().request
    sequence.advance(frame, now=now[0])
    assert manager.snapshot().action.skill_id == "navigate_to"
    assert manager.snapshot().action.destination_id == "mesa_sala"
