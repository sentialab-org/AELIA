from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator

from polyverse.contracts.actions import CandidateActionType
from polyverse.contracts.common import NonEmptyId, Provenance, StrictModel


class GoalSource(StrEnum):
    USER_REQUEST = "user_request"
    DRIVE_PRESSURE = "drive_pressure"
    APPRAISAL = "appraisal"
    COMMITMENT = "commitment"
    UNRESOLVED_QUESTION = "unresolved_question"
    INITIATIVE = "initiative"
    MAINTENANCE = "maintenance"


class GoalStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class Goal(StrictModel):
    goal_id: NonEmptyId
    source: GoalSource
    description: Annotated[str, Field(min_length=1, max_length=2048)]
    success_condition: Annotated[str, Field(min_length=1, max_length=2048)]
    priority: Annotated[float, Field(ge=0.0, le=1.0)]
    urgency: Annotated[float, Field(ge=0.0, le=1.0)]
    status: GoalStatus
    deadline: datetime | None = None
    parent_goal_id: NonEmptyId | None = None
    progress: Annotated[float, Field(ge=0.0, le=1.0)]
    owner: NonEmptyId
    conflict_set: tuple[NonEmptyId, ...]
    allowed_actions: tuple[CandidateActionType, ...]
    provenance: Provenance
    created_at: datetime
    updated_at: datetime

    @field_validator("deadline", "created_at", "updated_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("goal timestamps must include a timezone")
        return value.astimezone(UTC)


class GoalChange(StrictModel):
    goal_id: NonEmptyId
    status_before: GoalStatus | None
    status_after: GoalStatus
    reason_code: str


class GoalTransition(StrictModel):
    policy_version: str
    before: tuple[Goal, ...]
    after: tuple[Goal, ...]
    changes: tuple[GoalChange, ...]
