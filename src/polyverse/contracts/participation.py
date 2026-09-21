from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from polyverse.contracts.common import NonEmptyId, StrictModel


class AttentionLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProcessingMode(StrEnum):
    LIGHTWEIGHT = "lightweight"
    FULL = "full"


class ParticipationOutcome(StrEnum):
    OBSERVE = "observe"
    SILENT = "silent"
    WAIT = "wait"
    REPLY = "reply"
    REACT = "react"
    JOIN = "join"
    INITIATE = "initiate"
    INTERNAL_ACTION = "internal_action"


class ScoreBreakdown(StrictModel):
    direct_mention: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    direct_message: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    reply_to_agent: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    goal_domain_relevance: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    low_value_chatter: Annotated[float, Field(ge=-1.0, le=0.0)] = 0.0
    recent_participation_penalty: Annotated[float, Field(ge=-1.0, le=0.0)] = 0.0
    conversation_owned_by_others: Annotated[float, Field(ge=-1.0, le=0.0)] = 0.0
    persona_preference: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    internal_dynamics: Annotated[float, Field(ge=-1.0, le=1.0)] = 0.0
    total: Annotated[float, Field(ge=-3.0, le=4.0)]

    @model_validator(mode="after")
    def validate_total(self) -> ScoreBreakdown:
        calculated = (
            self.direct_mention
            + self.direct_message
            + self.reply_to_agent
            + self.goal_domain_relevance
            + self.low_value_chatter
            + self.recent_participation_penalty
            + self.conversation_owned_by_others
            + self.persona_preference
            + self.internal_dynamics
        )
        if abs(calculated - self.total) > 1e-9:
            raise ValueError("score breakdown total does not equal its components")
        return self


class AttentionResult(StrictModel):
    policy_version: Annotated[str, Field(min_length=1, max_length=64)]
    level: AttentionLevel
    processing_mode: ProcessingMode
    reason_codes: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...]
    score_breakdown: ScoreBreakdown
    full_cycle_threshold: Annotated[float, Field(ge=-3.0, le=4.0)]


class ParticipationDecision(StrictModel):
    cycle_id: NonEmptyId
    outcome: ParticipationOutcome
    reason_codes: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...]
    score_breakdown: ScoreBreakdown
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    policy_version: Annotated[str, Field(min_length=1, max_length=64)]
