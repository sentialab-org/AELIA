from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from polyverse.contracts.common import (
    NonEmptyId,
    Provenance,
    ProvenanceKind,
    StrictModel,
)


class MemoryCategory(StrEnum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    SOCIAL = "social"
    AUTOBIOGRAPHICAL = "autobiographical"
    PROCEDURAL = "procedural"
    COMMITMENT = "commitment"


class MemoryValidationStatus(StrEnum):
    OBSERVED = "observed"
    PROVISIONAL = "provisional"
    VALIDATED = "validated"
    REJECTED = "rejected"


class MemoryRecord(StrictModel):
    memory_id: NonEmptyId
    category: MemoryCategory
    scope_id: NonEmptyId
    canonical_source_type: str
    canonical_source_id: NonEmptyId
    summary: Annotated[str, Field(min_length=1, max_length=4096)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    validation_status: MemoryValidationStatus
    importance: Annotated[float, Field(ge=0.0, le=1.0)]
    source_event_ids: tuple[NonEmptyId, ...]
    provenance: Provenance
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("memory timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_record(self) -> MemoryRecord:
        if self.updated_at < self.created_at:
            raise ValueError("memory updated_at must not precede created_at")
        if len(self.source_event_ids) != len(set(self.source_event_ids)):
            raise ValueError("memory source_event_ids must be unique")
        if (
            self.category is MemoryCategory.SEMANTIC
            and self.provenance.kind is ProvenanceKind.MODEL
            and self.validation_status is MemoryValidationStatus.VALIDATED
        ):
            raise ValueError("model-derived semantic memory requires external validation")
        return self


class MemoryWriteSet(StrictModel):
    policy_version: str
    records: tuple[MemoryRecord, ...]
    reason_codes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_write_set(self) -> MemoryWriteSet:
        identities = [
            (record.category, record.canonical_source_type, record.canonical_source_id)
            for record in self.records
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("memory write set contains duplicate canonical references")
        if any(record.category is MemoryCategory.WORKING for record in self.records):
            raise ValueError("working memory is a conversation-buffer projection, not a record")
        return self


class MemoryCategoryWeight(StrictModel):
    category: MemoryCategory
    weight: Annotated[float, Field(ge=0.0, le=1.0)]
    reason_codes: tuple[str, ...]


class MemoryQuery(StrictModel):
    query_id: NonEmptyId
    scope_ids: Annotated[tuple[NonEmptyId, ...], Field(min_length=1)]
    categories: Annotated[tuple[MemoryCategory, ...], Field(min_length=1)]
    category_weights: Annotated[tuple[MemoryCategoryWeight, ...], Field(min_length=1)]
    limit: Annotated[int, Field(ge=1, le=100)]
    reason_codes: tuple[str, ...]
    provenance: Provenance

    @model_validator(mode="after")
    def validate_query(self) -> MemoryQuery:
        if len(self.scope_ids) != len(set(self.scope_ids)):
            raise ValueError("memory query scope_ids must be unique")
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("memory query categories must be unique")
        weighted_categories = [weight.category for weight in self.category_weights]
        if len(weighted_categories) != len(set(weighted_categories)):
            raise ValueError("memory query category weights must be unique")
        if set(weighted_categories) != set(self.categories):
            raise ValueError("memory query must define one weight per category")
        return self


class MemoryRetrievalItem(StrictModel):
    memory: MemoryRecord
    score: Annotated[float, Field(ge=0.0, le=1.0)]
    reason_codes: tuple[str, ...]
    provenance: Provenance


class MemoryRetrievalResult(StrictModel):
    policy_version: str
    query: MemoryQuery
    items: tuple[MemoryRetrievalItem, ...]
    vector_index_used: Literal[False]

    @model_validator(mode="after")
    def validate_result(self) -> MemoryRetrievalResult:
        memory_ids = [item.memory.memory_id for item in self.items]
        if len(memory_ids) != len(set(memory_ids)):
            raise ValueError("memory retrieval items must be unique")
        if len(self.items) > self.query.limit:
            raise ValueError("memory retrieval exceeds query limit")
        if any(
            item.memory.scope_id not in self.query.scope_ids
            or item.memory.category not in self.query.categories
            for item in self.items
        ):
            raise ValueError("memory retrieval item does not match query")
        if any(
            left.score < right.score
            for left, right in zip(self.items, self.items[1:], strict=False)
        ):
            raise ValueError("memory retrieval items must be ordered by descending score")
        return self


class OutcomeStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SIMULATED = "simulated"
    NO_ACTION = "no_action"


class OutcomeEvaluation(StrictModel):
    policy_version: str
    cycle_id: NonEmptyId
    status: OutcomeStatus
    expected_outcome: str
    observed_outcome: str
    goal_progress: Annotated[float, Field(ge=0.0, le=1.0)]
    social_effect: Annotated[float, Field(ge=-1.0, le=1.0)]
    drive_satisfaction: Annotated[float, Field(ge=-1.0, le=1.0)]
    prediction_error: Annotated[float, Field(ge=0.0, le=1.0)]
    reason_codes: tuple[str, ...]
    provenance: Provenance


class LearningTarget(StrEnum):
    BELIEF = "belief"
    RELATIONSHIP = "relationship"
    RETRIEVAL_WEIGHT = "retrieval_weight"
    STRATEGY = "strategy"


class ProposalStatus(StrEnum):
    PENDING_VALIDATION = "pending_validation"
    APPROVED = "approved"
    REJECTED = "rejected"


class LearningProposal(StrictModel):
    proposal_id: NonEmptyId
    target: LearningTarget
    target_id: NonEmptyId
    proposed_change: str
    evidence_ids: tuple[NonEmptyId, ...]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    reason_codes: tuple[str, ...] = ()
    status: ProposalStatus
    requires_validation: bool
    provenance: Provenance

    @model_validator(mode="after")
    def validate_proposal(self) -> LearningProposal:
        if self.status is ProposalStatus.PENDING_VALIDATION and not self.requires_validation:
            raise ValueError("pending learning proposals must require validation")
        if not self.evidence_ids:
            raise ValueError("learning proposal requires evidence")
        return self


class ReflectionTriggerType(StrEnum):
    EXECUTION_FAILURE = "execution_failure"
    BELIEF_CONFLICT = "belief_conflict"
    RELATIONSHIP_CHANGE = "relationship_change"
    COMMITMENT_VIOLATION = "commitment_violation"
    IDENTITY_RELEVANT = "identity_relevant"


class ReflectionTrigger(StrictModel):
    trigger_id: NonEmptyId
    trigger_type: ReflectionTriggerType
    severity: Annotated[float, Field(ge=0.0, le=1.0)]
    reason_codes: tuple[str, ...]
    evidence_ids: tuple[NonEmptyId, ...]
    requires_validation: bool

    @model_validator(mode="after")
    def validate_trigger(self) -> ReflectionTrigger:
        if not self.requires_validation:
            raise ValueError("reflection triggers cannot mutate important state directly")
        if not self.evidence_ids:
            raise ValueError("reflection trigger requires evidence")
        return self
