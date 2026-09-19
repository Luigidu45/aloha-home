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

"""Single-owner F5 supervisor. Inference never holds the mission manager lock."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from dimos.experimental.household_assistant.assessment import assess_requirements, resolve_target
from dimos.experimental.household_assistant.configuration import PilotConfiguration
from dimos.experimental.household_assistant.contracts import (
    ActionProposal,
    MissionRequest,
    Origin,
    Predicate,
    Verdict,
)
from dimos.experimental.household_assistant.mission_contracts import Arm, MissionSnapshot
from dimos.experimental.household_assistant.mission_verification import stopped
from dimos.experimental.household_assistant.planner_backend import pack_image
from dimos.experimental.household_assistant.planner_contracts import (
    BackendReply,
    PlannerConfig,
    PlannerContext,
    PlannerDecision,
)
from dimos.experimental.household_assistant.planner_options import (
    available_actions,
    missing_request_slots,
    needs_visual_clarification,
)
from dimos.msgs.sensor_msgs.Image import Image

PROMPT_PATH = Path(__file__).with_name("configs") / "planner_prompt.txt"
CONFIG_PATH = Path(__file__).with_name("configs") / "planner_cpu.json"


class VisualBackend(Protocol):
    def submit(
        self,
        prompt: str,
        images: list[dict[str, Any]],
        *,
        active_mission: bool,
        action_options: list[dict[str, Any]],
    ) -> None: ...
    def poll(self) -> BackendReply | None: ...
    def close(self) -> None: ...


class PlannerMissionPort(Protocol):
    pilot: PilotConfiguration
    arm: Arm
    max_age_s: float

    def snapshot(self) -> MissionSnapshot: ...
    def ask(self, reason: str, *, now: float) -> None: ...
    def admit_planner(
        self,
        *,
        expected: MissionSnapshot,
        request: MissionRequest | None,
        action: ActionProposal | None,
        question: str | None,
        target: str | None,
        now: float,
    ) -> MissionSnapshot: ...


def prompt_for(context: PlannerContext, template: str, options: tuple[ActionProposal, ...]) -> str:
    # Keep current facts separate from historical memory and preserve their origins.
    compact = {
        "mode": "NEXT_ACTION" if context.request else "INTERPRET_NEW_REQUEST",
        "instruction": context.instruction,
        "request": {
            "source": context.request.source_id,
            "destination": context.request.destination_id,
        }
        if context.request
        else None,
        "state": context.state.model_dump(mode="json", exclude_none=True),
        "current_facts": {
            "base_at": [
                o.key.place_id
                for o in context.world.observations
                if o.key.subject_id == "base"
                and o.key.predicate == Predicate.AT
                and o.value is True
            ],
            "base_aligned_at": [
                o.key.place_id
                for o in context.world.observations
                if o.key.subject_id == "base"
                and o.key.predicate == Predicate.ALIGNED
                and o.value is True
            ],
            "verified_held_object": context.state.held_object_id,
            "transport_ready_objects": [
                o.key.subject_id
                for o in context.world.observations
                if o.key.predicate == Predicate.TRANSPORT_READY and o.value is True
            ],
            "visible_bound_objects": [
                o.key.subject_id
                for o in context.world.observations
                if o.key.predicate == Predicate.VISIBLE and o.value is True
            ],
            "selected_object": context.state.selected_object_id,
            "completed_skills": context.state.completed_actions,
            "origins": sorted(
                {e.origin.value for o in context.world.observations for e in o.evidence}
            ),
        },
        "images": [{"id": v.id, "place": v.place_id} for v in context.views],
        "perception": [
            {
                "view": o.view.id,
                "status": o.status,
                "candidates": [c.model_dump() for c in o.candidates],
            }
            for o in context.perception
        ],
        "memory_historical_only": [
            {
                "view": c.view.id,
                "place": c.view.place_id,
                "captured_at": c.view.evidence.captured_at,
                "distance": c.cosine_distance,
            }
            for c in context.memory
        ],
        "previous_result": context.previous_result,
        "catalog": [s.id for s in context.catalog],
        "allowed_actions_now": [
            {"skill": a.skill_id, "destination": a.destination_id, "object_id": a.object_id}
            for a in options
        ],
    }
    return template + "\nCONTEXT_DATA_JSON:\n" + json.dumps(compact, ensure_ascii=False)


def parse_decision(raw: str) -> PlannerDecision:
    # No regex extraction, coercion, JSON repair or execution of generated code.
    return PlannerDecision.model_validate_json(raw)


def scene_signature(context: PlannerContext) -> str:
    facts = sorted(
        [(o.key.model_dump_json(), o.value) for o in context.world.observations], key=lambda x: x[0]
    )
    images = [(v.rgb_sha256, v.evidence.frame_id, v.place_id, v.map_id) for v in context.views]
    return hashlib.sha256(json.dumps([facts, images]).encode()).hexdigest()


def check_current(
    context: PlannerContext, images: tuple[Image, ...], *, now: float, max_age_s: float
) -> None:
    frame = context.world
    if not frame.connected or not 0 <= now - frame.captured_at <= max_age_s:
        raise ValueError("world is disconnected or stale")
    if context.state.revision != frame.revision:
        raise ValueError("state and world revisions differ")
    if context.state.action or context.state.state not in {"idle", "preparing", "searching"}:
        raise ValueError("planner requires an idle action slot")
    ready = assess_requirements(
        stopped(),
        frame.observations,
        now=now,
        clock_id=frame.clock_id,
        max_age_s=max_age_s,
        allowed_origins=frozenset({Origin.TEST, Origin.SIMULATION}),
    )
    if ready.verdict != Verdict.SUCCESS:
        raise ValueError("all actuators must be freshly observed stopped during inference")
    if len(images) != len(context.views) or len({v.id for v in context.views}) != len(images):
        raise ValueError("image/view count mismatch or duplicate IDs")
    for view, image in zip(context.views, images, strict=True):
        view.validate_image(image)
        if view.evidence.clock_id != frame.clock_id or not 0 <= now - image.ts <= max_age_s:
            raise ValueError("image evidence is stale or from another clock")
    if context.request and context.request.id != context.state.request_id:
        raise ValueError("request does not match mission state")


@dataclass(frozen=True)
class PendingDecision:
    context: PlannerContext
    started_at: float
    signature: str


class PlannerSupervisor:
    """Caller owns polling and backend lifecycle; manager cancellation stays independent."""

    def __init__(
        self, manager: PlannerMissionPort, backend: VisualBackend, config: PlannerConfig
    ) -> None:
        self.manager = manager
        self.backend = backend
        self.config = config
        self.template = PROMPT_PATH.read_text()
        self.pending: PendingDecision | None = None
        self.records: list[dict[str, Any]] = []
        self.last_decision: PlannerDecision | None = None
        self.request: MissionRequest | None = None
        self._steps = 0

    def begin(self, context: PlannerContext, images: tuple[Image, ...], *, now: float) -> None:
        if self.pending:
            raise RuntimeError("decision already pending")
        if self._steps >= 24:
            raise RuntimeError("decision budget exhausted; operator review required")
        check_current(context, images, now=now, max_age_s=self.config.max_image_age_s)
        if self.manager.snapshot() != context.state:
            raise ValueError("mission changed before inference")
        if any(s.id == "pick_remote_from_floor" for s in context.catalog):
            raise ValueError("expansion B is not available in F5")
        options = available_actions(self.manager.pilot, context, max_age_s=self.manager.max_age_s)
        self.pending = PendingDecision(context, now, scene_signature(context))
        try:
            self.backend.submit(
                prompt_for(context, self.template, options),
                [
                    pack_image(view, image)
                    for view, image in zip(context.views, images, strict=True)
                ],
                active_mission=context.request is not None,
                action_options=[
                    {"skill": a.skill_id, "destination": a.destination_id, "object_id": a.object_id}
                    for a in options
                ],
            )
        except (RuntimeError, ValueError, OSError):
            self.pending = None
            raise
        self._steps += 1
        self.records.append(
            {
                "event": "input",
                "at": now,
                "context": context.model_dump(mode="json"),
                "prompt_sha256": hashlib.sha256(self.template.encode()).hexdigest(),
                "config": self.config.model_dump(mode="json"),
            }
        )

    def poll(self, context: PlannerContext, images: tuple[Image, ...], *, now: float) -> str:
        pending = self.pending
        if pending is None:
            return "idle"
        # Check cancellation, payload, task progress and image changes even while model is busy.
        if self.manager.snapshot() != pending.context.state:
            return self._discard("mission_changed", now)
        try:
            check_current(context, images, now=now, max_age_s=self.config.max_image_age_s)
            if scene_signature(context) != pending.signature:
                return self._discard("scene_changed", now)
            if now - pending.started_at >= self.config.timeout_s:
                raise TimeoutError("decision expired")
            reply = self.backend.poll()
            if reply is None:
                return "pending"
            expected = [(v.id, v.rgb_sha256) for v in pending.context.views]
            if [
                (r.view_id, r.rgb_sha256) for r in reply.receipts
            ] != expected or not reply.tensor_shape:
                raise ValueError("backend did not acknowledge the supplied image pixels")
            self.records.append(
                {"event": "inference", "at": now, "reply": reply.model_dump(mode="json")}
            )
            decision = parse_decision(reply.raw)
            if tuple(decision.views) != tuple(v.id for v in pending.context.views):
                raise ValueError("decision cites an unknown or incomplete image set")
            at_source = bool(
                context.request
                and any(
                    o.key.subject_id == "base"
                    and o.key.predicate == Predicate.AT
                    and o.key.place_id == context.request.source_id
                    and o.value is True
                    for o in context.world.observations
                )
            )
            if decision.kind == "action" and needs_visual_clarification(
                reply.visual_assessment,
                at_source=at_source,
                held=context.state.held_object_id,
                selected=context.state.selected_object_id,
            ):
                raise ValueError("visual ambiguity/uncertainty requires clarification")
            self._admit(decision, context, pending.context, now)
        except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
            self.backend.close()
            self.pending = None
            self.records.append({"event": "rejected", "at": now, "reason": str(exc)})
            state = self.manager.snapshot()
            if state.state in {"preparing", "searching"} and state.action is None:
                self.manager.ask(f"VLM: {exc}. Revisa la escena o reformula la solicitud.", now=now)
            return "rejected"
        self.pending = None
        self.last_decision = decision
        self.records.append(
            {"event": "admitted", "at": now, "decision": decision.model_dump(mode="json")}
        )
        return "admitted"

    def _discard(self, reason: str, now: float) -> str:
        self.backend.close()
        self.pending = None
        self.records.append({"event": "discarded", "at": now, "reason": reason})
        return "discarded"

    def _admit(
        self,
        decision: PlannerDecision,
        current: PlannerContext,
        original: PlannerContext,
        now: float,
    ) -> None:
        action = None
        request = None
        target = None
        if decision.kind == "request":
            if original.request is not None:
                raise ValueError("cannot replace an active request")
            if missing_request_slots(original.instruction):
                raise ValueError("request must explicitly identify the object and destination")
            request = MissionRequest(
                id="vlm_" + uuid4().hex,
                mission_id="bring_bottle",
                instruction=original.instruction,
                object_category="small_bottle",
                source_id="mesa_sala",
                destination_id="mesa_dormitorio",
            )
        elif decision.kind == "action":
            if original.request is None:
                raise ValueError("action requires an accepted mission")
            options = available_actions(
                self.manager.pilot, current, max_age_s=self.manager.max_age_s
            )
            if (decision.skill, decision.destination, decision.object_id) not in {
                (a.skill_id, a.destination_id, a.object_id) for a in options
            }:
                raise ValueError("proposal is outside currently admissible skill parameters")
            if decision.skill in {"navigate_to", "align_at"}:
                required_destination = (
                    original.request.destination_id
                    if current.state.held_object_id
                    else original.request.source_id
                )
                if decision.destination != required_destination:
                    raise ValueError(
                        "navigation/alignment destination conflicts with verified payload"
                    )
            if (
                decision.skill == "pick_bottle_from_table"
                and current.state.selected_object_id is None
            ):
                resolved = resolve_target(
                    self.manager.pilot,
                    original.request,
                    current.world.observations,
                    now=now,
                    clock_id=current.world.clock_id,
                    max_age_s=self.manager.max_age_s,
                    allowed_origins=frozenset({Origin.TEST, Origin.SIMULATION}),
                )
                if resolved.status != "selected" or resolved.candidates != (decision.object_id,):
                    raise ValueError(
                        "pickup requires a unique current object binding or user selection"
                    )
                target = decision.object_id
            assert decision.skill is not None and decision.destination is not None
            action = ActionProposal(
                id="vlm_" + uuid4().hex,
                request_id=original.request.id,
                skill_id=decision.skill,
                destination_id=decision.destination,
                object_id=decision.object_id,
                arm=self.manager.arm if decision.object_id else None,
            )
        self.manager.admit_planner(
            expected=original.state,
            request=request,
            action=action,
            question=decision.question,
            target=target,
            now=now,
        )
        if request:
            self.request = request

    def cancel_pending(self, *, now: float) -> str:
        """Invalidate even a NEW request, for which the mission manager is still idle.

        The owner also requests mission cancellation through its independent control
        channel. A late interpretation must never submit a mission after this call.
        """
        return self._discard("operator_cancel", now) if self.pending else "idle"

    def close(self) -> None:
        self.backend.close()
        self.pending = None
