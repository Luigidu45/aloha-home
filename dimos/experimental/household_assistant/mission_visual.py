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

"""F3 pixels to F4 visibility, with explicit instance associations and no invented 3D pose."""

from dimos.experimental.household_assistant.configuration import PilotConfiguration
from dimos.experimental.household_assistant.contracts import Observation, Predicate
from dimos.experimental.household_assistant.mission_verification import fact
from dimos.experimental.household_assistant.visual import VisualObservation


def visibility_from_visual(
    pilot: PilotConfiguration,
    observation: VisualObservation,
    candidate_objects: dict[str, str],
) -> tuple[Observation, ...]:
    """Preserve capture evidence and uncertainty for unassociated catalog instances.

    `candidate_objects` is an explicit association supplied by a caller/operator;
    YOLO/CLIP alone do not establish persistent instance identity. This function
    never emits AT/INSIDE/HELD facts. A region association needs separate evidence
    before the manager can pick. In particular, an observer pose is not object 3D.
    """
    candidates = {c.id for c in observation.candidates}
    objects = {o.id for o in pilot.objects if o.category == observation.category}
    if not set(candidate_objects) <= candidates or not set(candidate_objects.values()) <= objects:
        raise ValueError("association must match this frame and requested object category")
    if len(set(candidate_objects.values())) != len(candidate_objects):
        raise ValueError("two candidates cannot be silently merged into one instance")
    visible = set(candidate_objects.values())
    return tuple(
        Observation(
            key=fact(obj.id, Predicate.VISIBLE),
            value=True if obj.id in visible else None,
            evidence=(observation.view.evidence,),
        )
        for obj in pilot.objects
        if obj.category == observation.category
    )
