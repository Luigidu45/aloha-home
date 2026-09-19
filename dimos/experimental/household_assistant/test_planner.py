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

"""Model boundary doubles test admission; they are not F5 VLM acceptance evidence."""

import hashlib
import json

from lmformatenforcer import JsonSchemaParser
from lmformatenforcer.characterlevelparser import CharacterLevelParserConfig
from lmformatenforcer.consts import COMPLETE_ALPHABET
import numpy as np
import pytest

from dimos.experimental.household_assistant.contracts import Evidence, Origin
from dimos.experimental.household_assistant.mission import MissionManager
from dimos.experimental.household_assistant.mission_sequence import MissionSequence
from dimos.experimental.household_assistant.mission_simulation import (
    ArtificialMissionExecutor,
    simulation_bindings,
)
from dimos.experimental.household_assistant.planner import PlannerSupervisor, parse_decision
from dimos.experimental.household_assistant.planner_backend import LocalVLM, pack_image
from dimos.experimental.household_assistant.planner_contracts import (
    BackendReply,
    PixelReceipt,
    PlannerConfig,
    PlannerContext,
    generation_schema,
)
from dimos.experimental.household_assistant.planner_grammar import decision_parser
from dimos.experimental.household_assistant.planner_options import available_actions
from dimos.experimental.household_assistant.spatial import PoseSample
from dimos.experimental.household_assistant.visual import ObservedView, rgb_digest
from dimos.msgs.sensor_msgs.Image import Image, ImageFormat


@pytest.fixture
def planner(pilot, request_a, mocker):
    manager = MissionManager(pilot, simulation_bindings(pilot), clock_id="test")
    driver = ArtificialMissionExecutor(manager)
    world = driver.step(now=100)
    manager.submit(request_a, now=100)
    image = Image(
        data=np.zeros((4, 4, 3), dtype=np.uint8), format=ImageFormat.RGB, ts=100, frame_id="camera"
    )
    view = ObservedView(
        id="view_1",
        evidence=Evidence(
            origin=Origin.TEST,
            source="unit_test",
            reference="fixture",
            captured_at=100,
            clock_id="test",
            frame_id="camera",
        ),
        rgb_sha256=rgb_digest(image),
        observer_pose=PoseSample(ts=100, x=0, y=0, yaw=0, frame_id="world"),
        pose_source="test",
        map_id="test_map",
        place_id="mesa_sala",
    )
    context = PlannerContext(
        instruction=request_a.instruction,
        request=request_a,
        state=manager.snapshot(),
        world=world,
        views=(view,),
        catalog=tuple(s for s in pilot.skills if s.id != "pick_remote_from_floor"),
        previous_result="request_accepted",
    )
    backend = mocker.Mock()
    config = PlannerConfig(model_id="test_double", revision="test")
    supervisor = PlannerSupervisor(manager, backend, config)
    yield supervisor, backend, driver, context, image
    supervisor.close()


def answer(context, image, **changes):
    decision = {
        "kind": "action",
        "skill": "navigate_to",
        "destination": "mesa_sala",
        "object_id": None,
        "question": None,
        "reason": "go to pickup",
        "plan": ["navigate_to"],
        "views": ["view_1"],
    }
    decision.update(changes)
    payload = pack_image(context.views[0], image)
    return BackendReply(
        raw=json.dumps(decision),
        receipts=(
            PixelReceipt(
                view_id="view_1",
                rgb_sha256=context.views[0].rgb_sha256,
                png_sha256=hashlib.sha256(payload["png"]).hexdigest(),
            ),
        ),
        tensor_sha256="tensor",
        tensor_shape=(1, 3, 4, 4),
        elapsed_s=1,
        peak_rss_mib=10,
        generated_tokens=30,
        visual_assessment="1",
    )


def test_real_manager_admits_only_one_bounded_action(planner):
    supervisor, backend, _, context, image = planner
    backend.poll.return_value = answer(context, image)
    supervisor.begin(context, (image,), now=100)
    assert supervisor.poll(context, (image,), now=101) == "admitted"
    commands = supervisor.manager.take_commands()
    assert len(commands) == 1
    assert commands[0].action.skill_id == "navigate_to"
    assert supervisor.poll(context, (image,), now=101) == "idle"
    assert supervisor.manager.take_commands() == ()
    assert backend.submit.call_args.args[1][0]["png"].startswith(b"\x89PNG")


@pytest.mark.parametrize(
    "changes",
    [
        {"skill": "joint_move"},
        {"destination": "kitchen"},
        {"object_id": "bottle_99"},
        {"views": ["invented"]},
        {"joint_angles": [1, 2]},
        {"plan": ["pick_remote_from_floor"]},
    ],
)
def test_invalid_model_output_never_dispatches(planner, changes):
    supervisor, backend, _, context, image = planner
    backend.poll.return_value = answer(context, image, **changes)
    supervisor.begin(context, (image,), now=100)
    assert supervisor.poll(context, (image,), now=101) == "rejected"
    assert supervisor.manager.take_commands() == ()
    assert supervisor.manager.snapshot().state == "asking"


def test_cancelled_mission_discards_model_reply(planner):
    supervisor, backend, driver, context, image = planner
    backend.poll.return_value = answer(context, image)
    supervisor.begin(context, (image,), now=100)
    supervisor.manager.cancel(now=100.1)
    assert supervisor.poll(context, (image,), now=100.2) == "discarded"
    backend.poll.assert_not_called()
    assert all(c.kind == "stop" for c in supervisor.manager.take_commands())


def test_changed_pixels_discard_even_without_world_revision_change(planner):
    supervisor, backend, _, context, image = planner
    supervisor.begin(context, (image,), now=100)
    changed = Image(
        data=np.ones((4, 4, 3), dtype=np.uint8), format=ImageFormat.RGB, ts=100, frame_id="camera"
    )
    view = context.views[0].model_copy(update={"rgb_sha256": rgb_digest(changed)})
    current = context.model_copy(update={"views": (view,)})
    assert supervisor.poll(current, (changed,), now=101) == "discarded"
    assert supervisor.manager.take_commands() == ()
    backend.poll.assert_not_called()


@pytest.mark.parametrize("failure", [TimeoutError("deadline"), RuntimeError("backend died")])
def test_backend_failure_leaves_question_and_no_action(planner, failure):
    supervisor, backend, _, context, image = planner
    backend.poll.side_effect = failure
    supervisor.begin(context, (image,), now=100)
    assert supervisor.poll(context, (image,), now=101) == "rejected"
    assert supervisor.manager.snapshot().state == "asking"
    assert supervisor.manager.take_commands() == ()


def test_missing_image_receipt_rejects_text_only_backend(planner):
    supervisor, backend, _, context, image = planner
    backend.poll.return_value = answer(context, image).model_copy(update={"receipts": ()})
    supervisor.begin(context, (image,), now=100)
    assert supervisor.poll(context, (image,), now=101) == "rejected"
    assert supervisor.manager.take_commands() == ()


def test_old_image_cannot_start_inference(planner):
    supervisor, backend, driver, context, image = planner
    world = driver.step(now=103)
    current = context.model_copy(update={"world": world, "state": supervisor.manager.snapshot()})
    with pytest.raises(ValueError, match="image evidence is stale"):
        supervisor.begin(current, (image,), now=103)
    backend.submit.assert_not_called()


def test_corrupted_pixels_cannot_start_inference(planner):
    supervisor, backend, _, context, image = planner
    image.data[:] = 255
    with pytest.raises(ValueError, match="does not match"):
        supervisor.begin(context, (image,), now=100)
    backend.submit.assert_not_called()


def test_manager_atomic_gate_rejects_cancel_between_check_and_dispatch(planner):
    supervisor, _, _, context, _ = planner
    supervisor.manager.cancel(now=100.1)
    with pytest.raises(ValueError, match="mission changed"):
        supervisor.manager.admit_planner(
            expected=context.state,
            request=None,
            action=None,
            question="¿Cuál botella?",
            target=None,
            now=100.2,
        )
    assert supervisor.manager.snapshot().state == "stopping"


def test_markdown_and_non_json_are_not_repaired():
    with pytest.raises(ValueError):
        parse_decision('```json\n{"kind":"ask"}\n```')


def test_generation_schema_accepts_complete_spanish_question():
    answer = json.dumps(
        {
            "kind": "ask",
            "skill": None,
            "destination": None,
            "object_id": None,
            "question": "¿Cuál botella quieres, la roja o la azul?",
            "reason": "Ambigüedad visual",
            "plan": [],
            "views": ["rgb_4"],
        },
        ensure_ascii=False,
    )
    parser = JsonSchemaParser(
        generation_schema(),
        config=CharacterLevelParserConfig(alphabet=COMPLETE_ALPHABET + "¿áéíóúñü"),
    )
    for character in answer:
        assert character in parser.get_allowed_characters()
        parser = parser.add_character(character)
    assert parser.can_end()
    assert parse_decision(answer).question == "¿Cuál botella quieres, la roja o la azul?"


@pytest.fixture
def process_backend(mocker, tmp_path):
    (tmp_path / "config.json").write_text("{}")
    context = mocker.Mock()
    parent, child = mocker.Mock(), mocker.Mock()
    context.Pipe.return_value = parent, child
    parent.poll.return_value = True
    parent.recv.return_value = {"ready": True}
    process = context.Process.return_value
    process.is_alive.return_value = True
    mocker.patch(
        "dimos.experimental.household_assistant.planner_backend.mp.get_context",
        return_value=context,
    )
    clock = mocker.patch(
        "dimos.experimental.household_assistant.planner_backend.time.monotonic", return_value=100
    )
    backend = LocalVLM(PlannerConfig(model_id="boundary_double", revision="test"), tmp_path)
    backend.start()
    try:
        yield backend, parent, process, clock
    finally:
        backend.close()


def test_buffered_reply_at_deadline_is_never_read(process_backend):
    backend, connection, process, clock = process_backend
    backend.submit("test", [{"png": b"fixture"}])
    connection.recv.reset_mock()
    clock.return_value = 160
    with pytest.raises(TimeoutError):
        backend.poll()
    connection.recv.assert_not_called()
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert backend.poll() is None


def test_backend_disconnect_is_reported_and_closed(process_backend):
    backend, connection, process, _ = process_backend
    backend.submit("test", [{"png": b"fixture"}])
    connection.recv.side_effect = EOFError
    with pytest.raises(RuntimeError, match="disconnected"):
        backend.poll()
    process.terminate.assert_called_once()
    assert backend.poll() is None


def test_stale_stop_during_inference_never_dispatches(planner):
    supervisor, backend, _, context, image = planner
    supervisor.begin(context, (image,), now=100)
    backend.poll.return_value = answer(context, image)
    assert supervisor.poll(context, (image,), now=103) == "rejected"
    assert supervisor.manager.take_commands() == ()
    backend.poll.assert_not_called()


def test_delivery_navigation_requires_verified_payload(planner):
    supervisor, backend, _, context, image = planner
    backend.poll.return_value = answer(context, image, destination="mesa_dormitorio")
    supervisor.begin(context, (image,), now=100)
    assert supervisor.poll(context, (image,), now=101) == "rejected"
    assert supervisor.manager.take_commands() == ()


def test_two_logical_candidates_cannot_be_selected_by_model_without_user(planner):
    supervisor, backend, driver, context, image = planner
    driver.place = "mesa_sala"
    driver.aligned = "mesa_sala"
    driver.scenario = "ambiguous"
    world = driver.step(now=100.1)
    current = context.model_copy(update={"world": world, "state": supervisor.manager.snapshot()})
    backend.poll.return_value = answer(
        current, image, skill="pick_bottle_from_table", object_id="bottle_01"
    )
    supervisor.begin(current, (image,), now=100.1)
    assert supervisor.poll(current, (image,), now=100.2) == "rejected"
    assert supervisor.manager.snapshot().selected_object_id is None
    assert supervisor.manager.take_commands() == ()


def test_verified_payload_disables_pickup_and_enables_loaded_stow(planner):
    supervisor, _, driver, context, _ = planner
    sequence = MissionSequence(supervisor.manager, context.request)
    for step in range(1, 150):
        now = 100 + step / 10
        world = driver.step(now=now)
        if supervisor.manager.snapshot().held_object_id:
            break
        sequence.advance(world, now=now)
    assert supervisor.manager.snapshot().held_object_id == "bottle_01"
    current = context.model_copy(update={"world": world, "state": supervisor.manager.snapshot()})
    options = available_actions(supervisor.manager.pilot, current, max_age_s=2)
    assert [(a.skill_id, a.destination_id, a.object_id) for a in options] == [
        ("prepare_transport", "mesa_sala", "bottle_01")
    ]


def test_actual_generation_parser_supports_unicode_question_and_omitted_nulls():
    parser = decision_parser(active_mission=True)
    parser.config = CharacterLevelParserConfig(alphabet=COMPLETE_ALPHABET + "¿áéíóúñü")
    payload = '{"kind":"ask","question":"¿Cuál botella quieres?","views":["rgb_4"]}'
    for character in payload:
        assert character in parser.get_allowed_characters()
        parser = parser.add_character(character)
    assert parser.can_end()
    assert parse_decision(payload).kind == "ask"


def test_cancel_during_new_request_interpretation_cannot_submit_late_mission(planner, pilot):
    _, backend, _, context, image = planner
    manager = MissionManager(pilot, simulation_bindings(pilot), clock_id="test")
    driver = ArtificialMissionExecutor(manager)
    world = driver.step(now=100)
    context = context.model_copy(
        update={"request": None, "state": manager.snapshot(), "world": world}
    )
    supervisor = PlannerSupervisor(
        manager, backend, PlannerConfig(model_id="test", revision="test")
    )
    try:
        supervisor.begin(context, (image,), now=100)
        manager.cancel(now=100.1)
        assert supervisor.cancel_pending(now=100.1) == "discarded"
        assert supervisor.poll(context, (image,), now=100.2) == "idle"
        backend.poll.assert_not_called()
        assert manager.snapshot().state == "idle"
        assert manager.take_commands() == ()
    finally:
        supervisor.close()


@pytest.mark.parametrize(
    "instruction", ["Tráeme algo al dormitorio", "Lleva la botella", "Ayúdame"]
)
def test_missing_request_slots_cannot_be_filled_by_model_assumption(planner, pilot, instruction):
    _, backend, _, context, image = planner
    manager = MissionManager(pilot, simulation_bindings(pilot), clock_id="test")
    driver = ArtificialMissionExecutor(manager)
    world = driver.step(now=100)
    context = context.model_copy(
        update={
            "request": None,
            "instruction": instruction,
            "state": manager.snapshot(),
            "world": world,
        }
    )
    backend.poll.return_value = answer(
        context, image, kind="request", skill=None, destination="mesa_dormitorio", plan=[]
    )
    supervisor = PlannerSupervisor(
        manager, backend, PlannerConfig(model_id="test", revision="test")
    )
    try:
        supervisor.begin(context, (image,), now=100)
        assert supervisor.poll(context, (image,), now=100.1) == "rejected"
        assert manager.snapshot().request_id == ""
        assert manager.take_commands() == ()
    finally:
        supervisor.close()
