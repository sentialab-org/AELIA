from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from polyverse.contracts.events import InboundEvent
from tests.helpers import make_event


def test_event_round_trip_preserves_contract() -> None:
    event = make_event()

    restored = InboundEvent.model_validate_json(event.model_dump_json())

    assert restored == event
    assert restored.occurred_at.tzinfo is not None


def test_event_rejects_unknown_fields() -> None:
    payload: dict[str, Any] = make_event().model_dump(mode="json")
    payload["unexpected"] = "value"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        InboundEvent.model_validate(payload)


def test_event_requires_current_schema_version() -> None:
    payload: dict[str, Any] = make_event().model_dump(mode="json")
    payload["schema_version"] = "1.0.0"

    with pytest.raises(ValidationError, match=r"Input should be '2\.0\.0'"):
        InboundEvent.model_validate(payload)


def test_event_rejects_naive_timestamp() -> None:
    payload: dict[str, Any] = make_event().model_dump(mode="json")
    payload["occurred_at"] = datetime(2026, 7, 30, 0, 0)

    with pytest.raises(ValidationError, match="must include a timezone"):
        InboundEvent.model_validate(payload)


def test_event_rejects_identifier_whitespace() -> None:
    payload: dict[str, Any] = make_event().model_dump(mode="json")
    payload["event_id"] = " event-001 "

    with pytest.raises(ValidationError, match="surrounding whitespace"):
        InboundEvent.model_validate(payload)
