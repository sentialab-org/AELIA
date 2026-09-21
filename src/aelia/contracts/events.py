from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator

from aelia.contracts.common import NonEmptyId, StrictModel

EventSchemaVersion = Literal["2.0.0"]
CURRENT_EVENT_SCHEMA_VERSION: EventSchemaVersion = "2.0.0"


class Platform(StrEnum):
    DISCORD = "discord"
    DISCORD_SELFBOT = "discord_selfbot"
    TELEGRAM = "telegram"
    CLI = "cli"
    TEST = "test"


class ChannelType(StrEnum):
    DM = "dm"
    GROUP = "group"
    CHANNEL = "channel"
    THREAD = "thread"
    UNKNOWN = "unknown"


class EventType(StrEnum):
    MESSAGE_CREATED = "message_created"
    MESSAGE_UPDATED = "message_updated"
    MESSAGE_DELETED = "message_deleted"
    REACTION_ADDED = "reaction_added"
    REACTION_REMOVED = "reaction_removed"
    MEMBER_JOINED = "member_joined"
    MEMBER_LEFT = "member_left"
    TOOL_RESULT = "tool_result"
    SCHEDULED = "scheduled"
    INTERNAL = "internal"


class AttachmentKind(StrEnum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    LINK = "link"


class AttachmentReference(StrictModel):
    attachment_id: NonEmptyId
    kind: AttachmentKind
    mime_type: Annotated[str | None, Field(max_length=128)] = None
    filename: Annotated[str | None, Field(max_length=512)] = None
    source_url: Annotated[str | None, Field(max_length=4096)] = None
    size_bytes: Annotated[int | None, Field(ge=0)] = None


class ReplyReference(StrictModel):
    event_id: NonEmptyId
    actor_id: NonEmptyId | None = None


class PermissionContext(StrictModel):
    can_send_message: bool
    can_reply: bool
    can_react: bool
    is_private: bool
    scopes: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...] = ()


class SourceReference(StrictModel):
    adapter: Annotated[str, Field(min_length=1, max_length=128)]
    raw_event_id: NonEmptyId
    trace_id: NonEmptyId | None = None


class InboundEvent(StrictModel):
    schema_version: EventSchemaVersion
    event_id: NonEmptyId
    platform: Platform
    conversation_id: NonEmptyId
    channel_type: ChannelType
    actor_id: NonEmptyId
    occurred_at: datetime
    event_type: EventType
    content: Annotated[str | None, Field(max_length=100_000)] = None
    reply_to: ReplyReference | None = None
    mentions: tuple[NonEmptyId, ...] = ()
    attachments: tuple[AttachmentReference, ...] = ()
    permissions: PermissionContext
    source_reference: SourceReference

    @field_validator("occurred_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("event_id", "conversation_id", "actor_id")
    @classmethod
    def reject_surrounding_whitespace(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("identifier must not contain surrounding whitespace")
        return value
