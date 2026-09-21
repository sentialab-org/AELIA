from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from polyverse.cognition.memory import MemoryPolicy
from polyverse.contracts.common import Provenance, ProvenanceKind
from polyverse.models.cognition import InternalState
from polyverse.models.memory import (
    MemoryCategory,
    MemoryRecord,
    MemoryValidationStatus,
    MemoryWriteSet,
)
from polyverse.models.self_model import SelfModel
from tests.helpers import make_event

TIMESTAMP = datetime(2026, 7, 30, tzinfo=UTC)


def _record(
    *,
    category: MemoryCategory,
    provenance_kind: ProvenanceKind = ProvenanceKind.RULE,
    status: MemoryValidationStatus = MemoryValidationStatus.OBSERVED,
) -> MemoryRecord:
    return MemoryRecord(
        memory_id=f"memory:{category.value}",
        category=category,
        scope_id="actor:test:user-001",
        canonical_source_type="belief",
        canonical_source_id="belief:001",
        summary="Canonical reference.",
        confidence=0.8,
        validation_status=status,
        importance=0.5,
        source_event_ids=("event-001",),
        provenance=Provenance(
            kind=provenance_kind,
            source_id="event-001",
            method="unit-test",
            confidence=0.8,
            created_at=TIMESTAMP,
        ),
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )


def test_model_derived_semantic_memory_cannot_become_validated_fact() -> None:
    with pytest.raises(
        ValidationError,
        match="model-derived semantic memory requires external validation",
    ):
        _record(
            category=MemoryCategory.SEMANTIC,
            provenance_kind=ProvenanceKind.MODEL,
            status=MemoryValidationStatus.VALIDATED,
        )


def test_working_memory_cannot_be_persisted_as_a_memory_record() -> None:
    with pytest.raises(
        ValidationError,
        match="working memory is a conversation-buffer projection",
    ):
        MemoryWriteSet(
            policy_version="unit-test",
            records=(_record(category=MemoryCategory.WORKING),),
            reason_codes=("unit_test",),
        )


def test_internal_state_causally_modulates_memory_query_weights() -> None:
    self_model = SelfModel(
        model_version="test",
        persona_id="ryuuko",
        persona_specification_version="test",
        identity_fingerprint="fingerprint",
        identity_anchors=(),
        values=(),
        capabilities=(),
        limitations=(),
        commitments=(),
        slow_changing_beliefs=(),
    )
    baseline = InternalState.initial("persona:ryuuko")
    high_uncertainty_reduction = baseline.model_copy(
        update={"drives": baseline.drives.model_copy(update={"uncertainty_reduction": 1.0})}
    )
    policy = MemoryPolicy()

    baseline_query = policy.build_query(
        event=make_event(),
        self_model=self_model,
        internal=baseline,
    )
    modulated_query = policy.build_query(
        event=make_event(),
        self_model=self_model,
        internal=high_uncertainty_reduction,
    )
    baseline_semantic = next(
        weight.weight
        for weight in baseline_query.category_weights
        if weight.category is MemoryCategory.SEMANTIC
    )
    modulated_semantic = next(
        weight.weight
        for weight in modulated_query.category_weights
        if weight.category is MemoryCategory.SEMANTIC
    )

    assert modulated_semantic > baseline_semantic
    assert modulated_query.limit > baseline_query.limit
    assert "internal_state_modulates_retrieval" in modulated_query.reason_codes
