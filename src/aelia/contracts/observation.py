from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import Field, field_validator

from aelia.contracts.common import NonEmptyId, StrictModel
from aelia.contracts.events import ChannelType
from aelia.contracts.participation import ParticipationOutcome


class ConversationMessage(StrictModel):
    position: Annotated[int, Field(ge=1)]
    event_id: NonEmptyId
    actor_id: NonEmptyId
    occurred_at: datetime
    channel_type: ChannelType
    content: Annotated[str | None, Field(max_length=100_000)] = None
    reply_to_event_id: NonEmptyId | None = None
    reply_to_actor_id: NonEmptyId | None = None
    mentions: tuple[NonEmptyId, ...] = ()

    @field_validator("occurred_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)


class RecentParticipation(StrictModel):
    position: Annotated[int, Field(ge=1)]
    event_id: NonEmptyId
    outcome: ParticipationOutcome


class ObservationSnapshot(StrictModel):
    conversation_id: NonEmptyId
    agent_actor_id: NonEmptyId
    state_version: Annotated[int, Field(ge=0)]
    recent_messages: tuple[ConversationMessage, ...] = ()
    recent_participation: tuple[RecentParticipation, ...] = ()
