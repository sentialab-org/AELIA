from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

NonEmptyId = Annotated[str, Field(min_length=1, max_length=256)]


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class StrictModel(BaseModel):
    """Immutable model that rejects undeclared fields at module boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProvenanceKind(StrEnum):
    PLATFORM = "platform"
    RULE = "rule"
    MODEL = "model"
    TOOL = "tool"
    INTERNAL = "internal"


class Provenance(StrictModel):
    kind: ProvenanceKind
    source_id: NonEmptyId
    method: Annotated[str, Field(min_length=1, max_length=128)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(UTC)
