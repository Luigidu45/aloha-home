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

"""Versioned, jointly validated loading of mission and scenario configuration."""

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from dimos.experimental.domestic_assistance.contracts import Contract, Mission, Scenario, Sha256

CURRENT_CONFIG_SCHEMA_VERSION: Literal[1] = 1


class ConfigBundle(Contract):
    config_schema_version: Literal[1]
    mission: Mission
    scenario: Scenario
    mission_config_sha256: Sha256
    scenario_config_sha256: Sha256


def _load_versioned_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON configuration: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"configuration root must be an object: {path}")
    version = payload.get("config_schema_version")
    if version != CURRENT_CONFIG_SCHEMA_VERSION:
        raise ValueError(f"unsupported or missing config_schema_version in {path}: {version!r}")
    return raw, payload


def load_config_bundle(mission_path: Path, scenario_path: Path) -> ConfigBundle:
    """Load, hash and cross-validate one explicit mission/scenario pair."""
    mission_raw, mission_payload = _load_versioned_json(mission_path)
    scenario_raw, scenario_payload = _load_versioned_json(scenario_path)
    mission = Mission.model_validate(mission_payload)
    scenario = Scenario.model_validate(scenario_payload)
    scenario.validate_mission(mission)
    return ConfigBundle(
        config_schema_version=CURRENT_CONFIG_SCHEMA_VERSION,
        mission=mission,
        scenario=scenario,
        mission_config_sha256=hashlib.sha256(mission_raw).hexdigest(),
        scenario_config_sha256=hashlib.sha256(scenario_raw).hexdigest(),
    )
