from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from aelia.contracts.common import NonEmptyId, Provenance, StrictModel


class TurnOwnership(StrEnum):
    AGENT = "agent"
    OPEN = "open"
    OTHER = "other"
    UNCLAIMED = "unclaimed"


class ConversationModel(StrictModel):
    """Rebuildable conversation projection used by attention and turn-taking."""

    model_version: str
    conversation_id: NonEmptyId
    based_on_state_version: Annotated[int, Field(ge=0)]
    latest_event_id: NonEmptyId
    latest_actor_id: NonEmptyId
    active_speaker_ids: tuple[NonEmptyId, ...]
    topic_terms: tuple[Annotated[str, Field(min_length=1, max_length=64)], ...]
    current_event_is_question: bool
    open_invitation: bool
    directed_to_agent: bool
    directed_to_other: bool
    turn_ownership: TurnOwnership
    agent_expected_to_respond: bool
    another_participant_better_positioned: bool
    reason_codes: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...]
    provenance: Provenance
