from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from aelia.contracts.common import NonEmptyId, Provenance, StrictModel
from aelia.contracts.events import Platform


class WorldStatementKind(StrEnum):
    OBSERVATION = "observation"
    BELIEF_REFERENCE = "belief_reference"
    HYPOTHESIS = "hypothesis"
    CAPABILITY = "capability"
    PREDICTION = "prediction"


class WorldStatement(StrictModel):
    statement_id: NonEmptyId
    kind: WorldStatementKind
    subject: NonEmptyId
    predicate: NonEmptyId
    value: Annotated[str, Field(min_length=1, max_length=2048)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    source_ids: tuple[NonEmptyId, ...]


class WorldModel(StrictModel):
    """A rebuildable projection over canonical events and beliefs."""

    model_version: str
    scope_id: NonEmptyId
    platform: Platform
    current_event_id: NonEmptyId
    entity_ids: tuple[NonEmptyId, ...]
    statements: tuple[WorldStatement, ...]
    rebuildable: Literal[True]
    provenance: Provenance

    def capability_available(self, capability: str) -> bool:
        return any(
            statement.kind is WorldStatementKind.CAPABILITY
            and statement.predicate == capability
            and statement.value == "available"
            for statement in self.statements
        )
