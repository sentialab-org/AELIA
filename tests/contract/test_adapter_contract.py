from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from aelia.contracts.adapter import (
    AdapterDeliveryReceipt,
    AdapterInboundEnvelope,
    AdapterMode,
    AdapterOutboundCommand,
    AdapterPolicyConfig,
)
from tests.helpers import make_adapter_envelope


def test_adapter_envelope_round_trips_as_strict_versioned_json() -> None:
    envelope = make_adapter_envelope()

    restored = AdapterInboundEnvelope.model_validate_json(envelope.model_dump_json())
    schema = AdapterInboundEnvelope.model_json_schema()

    assert restored == envelope
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "1.0.0"


def test_adapter_contracts_are_independently_versioned() -> None:
    inbound = AdapterInboundEnvelope.model_json_schema()
    outbound = AdapterOutboundCommand.model_json_schema()
    receipt = AdapterDeliveryReceipt.model_json_schema()

    assert inbound["properties"]["schema_version"]["const"] == "1.0.0"
    assert outbound["properties"]["schema_version"]["const"] == "1.1.0"
    assert receipt["properties"]["schema_version"]["const"] == "1.1.0"


def test_adapter_envelope_rejects_unknown_version_and_source_mismatch() -> None:
    payload: dict[str, Any] = make_adapter_envelope().model_dump(mode="json")
    payload["schema_version"] = "0.9.0"
    with pytest.raises(ValidationError, match=r"Input should be '1\.0\.0'"):
        AdapterInboundEnvelope.model_validate(payload)

    payload = make_adapter_envelope().model_dump(mode="json")
    payload["adapter_id"] = "different-adapter"
    with pytest.raises(ValidationError, match="must match event source adapter"):
        AdapterInboundEnvelope.model_validate(payload)


def test_test_canary_requires_a_unique_explicit_allowlist() -> None:
    with pytest.raises(ValidationError, match="requires at least one conversation"):
        AdapterPolicyConfig(
            policy_version="test",
            mode=AdapterMode.TEST_CANARY,
            canary_conversation_ids=(),
            conversation_limit_per_hour=1,
        )
    with pytest.raises(ValidationError, match="requires at least one conversation"):
        AdapterPolicyConfig(
            policy_version="test",
            mode=AdapterMode.EXTERNAL_CANARY,
            canary_conversation_ids=(),
            conversation_limit_per_hour=1,
        )
    with pytest.raises(ValidationError, match="must be unique"):
        AdapterPolicyConfig(
            policy_version="test",
            mode=AdapterMode.TEST_CANARY,
            canary_conversation_ids=("conversation-1", "conversation-1"),
            conversation_limit_per_hour=1,
        )


def test_core_kernel_does_not_import_adapter_implementation() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src/aelia"
    core_directories = (
        root / "cognition",
        root / "models",
        root / "persona",
        root / "runtime",
    )
    core_sources = [
        path.read_text(encoding="utf-8")
        for directory in core_directories
        for path in directory.rglob("*.py")
    ]

    assert core_sources, "expected kernel sources so this check is not vacuous"
    assert all("aelia.adapters" not in source for source in core_sources)
    assert set(AdapterMode) == {
        AdapterMode.SHADOW,
        AdapterMode.TEST_CANARY,
        AdapterMode.EXTERNAL_CANARY,
    }
