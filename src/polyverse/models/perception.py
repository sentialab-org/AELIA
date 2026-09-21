from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from polyverse.contracts.common import NonEmptyId, Provenance, StrictModel


class PerceptionDepth(StrEnum):
    LIGHTWEIGHT = "lightweight"
    DEEP = "deep"


class EpistemicKind(StrEnum):
    OBSERVATION = "observation"
    INFERENCE = "inference"
    HYPOTHESIS = "hypothesis"


class ObservedSignal(StrictModel):
    observation_id: NonEmptyId
    kind: EpistemicKind
    statement: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    uncertainty: Annotated[float, Field(ge=0.0, le=1.0)]
    provenance: Provenance


class ClaimCandidate(StrictModel):
    claim_id: NonEmptyId
    subject: NonEmptyId
    predicate: NonEmptyId
    value: Annotated[str, Field(min_length=1, max_length=2048)]
    kind: EpistemicKind
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    uncertainty: Annotated[float, Field(ge=0.0, le=1.0)]
    evidence_observation_ids: tuple[NonEmptyId, ...]
    provenance: Provenance


class PerceptionResult(StrictModel):
    policy_version: str
    depth: PerceptionDepth
    observed_signals: tuple[ObservedSignal, ...]
    claim_candidates: tuple[ClaimCandidate, ...]
    uncertainty: Annotated[float, Field(ge=0.0, le=1.0)]
    reason_codes: tuple[str, ...]
