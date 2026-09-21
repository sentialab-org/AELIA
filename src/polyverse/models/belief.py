from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator

from polyverse.contracts.common import NonEmptyId, Provenance, StrictModel
from polyverse.models.perception import EpistemicKind


class BeliefStatus(StrEnum):
    PROVISIONAL = "provisional"
    ACCEPTED = "accepted"
    CONTESTED = "contested"
    REJECTED = "rejected"


class BeliefEvidence(StrictModel):
    event_id: NonEmptyId
    observation_id: NonEmptyId
    supports: bool
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    provenance: Provenance


class BeliefRecord(StrictModel):
    belief_id: NonEmptyId
    scope_id: NonEmptyId
    subject: NonEmptyId
    predicate: NonEmptyId
    value: Annotated[str, Field(min_length=1, max_length=2048)]
    epistemic_kind: EpistemicKind
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    status: BeliefStatus
    evidence: tuple[BeliefEvidence, ...]
    contradiction_links: tuple[NonEmptyId, ...]
    provenance: Provenance
    created_at: datetime
    updated_at: datetime
    decay_policy: str

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("belief timestamps must include a timezone")
        return value.astimezone(UTC)


class BeliefSnapshot(StrictModel):
    scope_id: NonEmptyId
    records: tuple[BeliefRecord, ...]


class BeliefTransition(StrictModel):
    policy_version: str
    before: BeliefSnapshot
    upserts: tuple[BeliefRecord, ...]
    reason_codes: tuple[str, ...]
