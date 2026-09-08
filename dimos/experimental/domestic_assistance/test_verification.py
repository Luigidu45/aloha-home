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

import pytest

from dimos.experimental.domestic_assistance.contracts import ComponentManifest
from dimos.experimental.domestic_assistance.verification import (
    DEFAULT_VERIFIER,
    VerifierRegistry,
)


def test_registry_resolves_the_exact_frozen_verifier():
    registry = VerifierRegistry((DEFAULT_VERIFIER,))
    component = ComponentManifest(
        name=DEFAULT_VERIFIER.name,
        version=DEFAULT_VERIFIER.version,
        sha256=DEFAULT_VERIFIER.fingerprint,
    )

    assert registry.resolve(component) is DEFAULT_VERIFIER
    assert len(DEFAULT_VERIFIER.fingerprint) == 64


def test_registry_can_resolve_a_legacy_manifest_without_a_fingerprint():
    registry = VerifierRegistry((DEFAULT_VERIFIER,))
    legacy = ComponentManifest(
        name=DEFAULT_VERIFIER.name,
        version=DEFAULT_VERIFIER.version,
    )

    assert registry.resolve(legacy) is DEFAULT_VERIFIER


def test_registry_rejects_unknown_versions_and_fingerprint_mismatches():
    registry = VerifierRegistry((DEFAULT_VERIFIER,))
    unknown = ComponentManifest(name="observed-facts", version="observed-facts-v1")
    mismatched = ComponentManifest(
        name=DEFAULT_VERIFIER.name,
        version=DEFAULT_VERIFIER.version,
        sha256="0" * 64,
    )

    with pytest.raises(ValueError, match="not registered"):
        registry.resolve(unknown)
    with pytest.raises(ValueError, match="fingerprint"):
        registry.resolve(mismatched)
