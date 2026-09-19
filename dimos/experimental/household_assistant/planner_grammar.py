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

"""Constrain the output vocabulary and phase; the supervisor checks cross-field semantics."""

from typing import Any

from lmformatenforcer import JsonSchemaParser

from dimos.experimental.household_assistant.planner_contracts import generation_schema


def decision_parser(
    active_mission: bool = True,
    action_options: list[dict[str, Any]] | None = None,
    *,
    request_allowed: bool = True,
) -> JsonSchemaParser:
    schema = generation_schema()
    schema["properties"]["kind"]["enum"] = (
        ["action", "ask"] if active_mission else ["request", "ask"]
    )
    if not active_mission and not request_allowed:
        schema["properties"]["kind"]["enum"] = ["ask"]
    if active_mission:
        if not action_options:
            schema["properties"]["kind"]["enum"] = ["ask"]
        else:
            schema["properties"]["skill"]["anyOf"][0]["enum"] = sorted(
                {a["skill"] for a in action_options}
            )
            schema["properties"]["destination"]["anyOf"][0]["enum"] = sorted(
                {a["destination"] for a in action_options}
            )
    return JsonSchemaParser(schema)
