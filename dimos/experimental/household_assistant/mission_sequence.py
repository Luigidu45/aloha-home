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

"""Deterministic F4 baseline and the F3 memory boundary; no generative planner."""

from dimos.experimental.household_assistant.assessment import (
    assess_completion,
    assess_requirements,
    resolve_target,
)
from dimos.experimental.household_assistant.contracts import (
    ActionProposal,
    MissionRequest,
    Operation,
    Origin,
    Predicate,
    Verdict,
    Verification,
)
from dimos.experimental.household_assistant.mission import MissionManager
from dimos.experimental.household_assistant.mission_contracts import WorldFrame
from dimos.experimental.household_assistant.mission_verification import (
    carrying,
    fact,
    postconditions,
)
from dimos.experimental.household_assistant.semantic_memory import (
    BoundedSearch,
    HouseholdMemory,
    load_catalog,
)


class MissionSequence:
    """One action per fresh admission. This baseline is not a VLM or an ACT policy."""

    def __init__(self, manager: MissionManager, request: MissionRequest) -> None:
        self.manager = manager
        self.request = request
        self._counter = 0
        hint = load_catalog(manager.pilot).target(request.object_category)
        # F1 fixes a source region for manipulation. Wider F3 memory hints require
        # an explicit mission/source revision; never silently change the pickup domain.
        self._search = BoundedSearch(
            hint.model_copy(update={"usual_places": (request.source_id,)}),
            (),
            max_places=1,
            views_per_place=2,
        )
        self._search.next()
        self._last_observe_count = 0

    def advance(self, frame: WorldFrame, *, now: float) -> None:
        snapshot = self.manager.snapshot()
        if snapshot.state != "preparing" or snapshot.action is not None:
            return
        destination = (
            self.request.destination_id if snapshot.held_object_id else self.request.source_id
        )
        at = assess_requirements(
            (fact("base", Predicate.AT, destination),),
            frame.observations,
            now=now,
            clock_id=self.manager.clock_id,
            max_age_s=self.manager.max_age_s,
            allowed_origins=frozenset({Origin.TEST, Origin.SIMULATION}),
        )
        skill: str
        if snapshot.held_object_id:
            ready = assess_requirements(
                carrying(snapshot.held_object_id, self.manager.arm),
                frame.observations,
                now=now,
                clock_id=self.manager.clock_id,
                max_age_s=self.manager.max_age_s,
                allowed_origins=frozenset({Origin.TEST, Origin.SIMULATION}),
            )
            if ready.verdict != Verdict.SUCCESS:
                skill = "prepare_transport"
                # Stow where the robot is currently stopped, including pause recovery.
                destination = (
                    self.request.destination_id
                    if at.verdict == Verdict.SUCCESS
                    else self.request.source_id
                )
            elif at.verdict != Verdict.SUCCESS:
                skill = "navigate_to"
            elif "align_delivery" not in self._completed_roles():
                skill = "align_at"
            else:
                skill = "place_on_table"
        elif at.verdict != Verdict.SUCCESS:
            skill = "navigate_to"
        elif "observe_at" not in snapshot.completed_actions:
            skill = "observe_at"
        elif snapshot.selected_object_id is None:
            target = resolve_target(
                self.manager.pilot,
                self.request,
                frame.observations,
                now=now,
                clock_id=self.manager.clock_id,
                max_age_s=self.manager.max_age_s,
                allowed_origins=frozenset({Origin.TEST, Origin.SIMULATION}),
            )
            if target.status == "selected":
                self.manager.select_target(
                    target.candidates[0],
                    expected_revision=snapshot.revision,
                    now=now,
                    by_user=False,
                )
                return
            count = snapshot.completed_actions.count("observe_at")
            if count == self._last_observe_count:
                return
            self._last_observe_count = count
            step = self._search.next(
                "ambiguous"
                if target.status == "ambiguous"
                else "absent"
                if target.status == "not_found"
                else "unknown"
            )
            if step.kind == "ask_user":
                self.manager.ask(f"{target.status}:{step.reason}", now=now)
                return
            skill = "observe_at"
        elif "align_pickup" not in self._completed_roles():
            skill = "align_at"
        else:
            skill = (
                self.manager.pilot.mission.pickup_skill_id
                if self.request.mission_id == self.manager.pilot.mission.id
                else self.manager.pilot.expansion.pickup_skill_id
            )
        manipulation = skill in {
            "prepare_transport",
            "place_on_table",
            "pick_bottle_from_table",
            "pick_remote_from_floor",
        }
        action = ActionProposal(
            id=f"{self.request.id}_action_{self._counter}",
            request_id=self.request.id,
            skill_id=skill,
            destination_id=destination,
            object_id=snapshot.selected_object_id if manipulation else None,
            arm=self.manager.arm if manipulation else None,
        )
        try:
            self.manager.propose(action, expected_revision=snapshot.revision, now=now)
        except ValueError as exc:
            self.manager.ask(f"admission_requires_clarification:{exc}", now=now)
        else:
            self._counter += 1

    def _completed_roles(self) -> set[str]:
        # Verified actions are joined to their dispatch, never inferred from motor callbacks.
        events = self.manager.events()
        dispatched = {
            e.command.action.id: e.command.action
            for e in events
            if e.command and e.command.kind == "start" and e.request_id == self.request.id
        }
        roles = set()
        resumed_at = max(
            (
                e.sequence
                for e in events
                if e.request_id == self.request.id
                and e.kind == "intervention"
                and e.detail == "resume_reprepared_not_replayed"
            ),
            default=-1,
        )
        for event in events:
            if (
                event.sequence > resumed_at
                and event.kind == "verification"
                and event.verification
                and event.verification.verdict == Verdict.SUCCESS
                and event.detail in dispatched
            ):
                action = dispatched[event.detail]
                if action.skill_id == "align_at":
                    roles.add(
                        "align_delivery"
                        if action.destination_id == self.request.destination_id
                        else "align_pickup"
                    )
        return roles


def record_verified_placement(
    memory: HouseholdMemory, manager: MissionManager, frame: WorldFrame, *, now: float
) -> Verification:
    """Only the manager's independently verified mission can update F3 placement memory."""
    execution = manager.completed_execution()
    snapshot = manager.snapshot()
    if execution is None or snapshot.selected_object_id is None:
        return Verification(verdict=Verdict.UNKNOWN, reason="mission_has_no_verified_placement")
    actions = [
        e.command.action
        for e in manager.events()
        if e.command and e.command.kind == "start" and e.command.action.id == execution.action_id
    ]
    verification = assess_completion(
        execution,
        postconditions(Operation.PLACE, actions[-1], snapshot.selected_object_id, manager.arm),
        frame.observations,
        now=now,
        clock_id=manager.clock_id,
        max_age_s=manager.max_age_s,
        allowed_origins=frozenset({Origin.TEST, Origin.SIMULATION}),
    )
    if verification.verdict != Verdict.SUCCESS:
        return verification
    return memory.verify_placement(
        manager.pilot,
        snapshot.selected_object_id,
        actions[-1].destination_id,
        manager.arm,
        execution,
        frame.observations,
        now=now,
        clock_id=manager.clock_id,
        allowed_origins=frozenset({Origin.TEST, Origin.SIMULATION}),
        max_age_s=manager.max_age_s,
    )
