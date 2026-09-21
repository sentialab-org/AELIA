from __future__ import annotations

import re

from polyverse.contracts.common import Provenance, ProvenanceKind
from polyverse.contracts.events import ChannelType, EventType, InboundEvent
from polyverse.contracts.observation import ObservationSnapshot
from polyverse.models.conversation import ConversationModel, TurnOwnership

CONVERSATION_POLICY_VERSION = "conversation-rules-v1"

_OPEN_INVITATION_PATTERNS = (
    re.compile(r"\bany(?:one|body)\b", re.IGNORECASE),
    re.compile(r"\bdoes anyone\b", re.IGNORECASE),
    re.compile(r"\bcan anyone\b", re.IGNORECASE),
    re.compile(r"\bai (?:biết|rành|giúp|có thể)\b", re.IGNORECASE),
    re.compile(r"\bcó ai\b", re.IGNORECASE),
    re.compile(r"\bmọi người\b", re.IGNORECASE),
    re.compile(r"\bmn\b", re.IGNORECASE),
)
_QUESTION_STARTERS = (
    "ai ",
    "có ai ",
    "làm sao ",
    "tại sao ",
    "vì sao ",
    "what ",
    "when ",
    "where ",
    "which ",
    "who ",
    "why ",
    "how ",
    "can ",
    "could ",
    "does ",
    "do ",
    "is ",
    "are ",
)
_TOPIC_STOPWORDS = frozenset(
    {
        "about",
        "again",
        "anyone",
        "could",
        "does",
        "giúp",
        "không",
        "mọi",
        "người",
        "please",
        "that",
        "this",
        "what",
        "when",
        "where",
        "which",
        "with",
        "would",
    }
)


class ConversationPolicy:
    def project(
        self,
        *,
        event: InboundEvent,
        observation: ObservationSnapshot,
    ) -> ConversationModel:
        content = " ".join((event.content or "").split())
        normalized = content.casefold()
        is_message = event.event_type is EventType.MESSAGE_CREATED
        is_question = is_message and (
            "?" in normalized or normalized.startswith(_QUESTION_STARTERS)
        )
        directed_to_agent = (
            event.channel_type is ChannelType.DM
            or observation.agent_actor_id in event.mentions
            or (
                event.reply_to is not None and event.reply_to.actor_id == observation.agent_actor_id
            )
        )
        directed_to_other = event.channel_type is not ChannelType.DM and (
            (
                event.reply_to is not None
                and event.reply_to.actor_id not in {None, observation.agent_actor_id}
            )
            or (bool(event.mentions) and observation.agent_actor_id not in event.mentions)
        )
        open_invitation = (
            is_question
            and event.channel_type in {ChannelType.GROUP, ChannelType.CHANNEL, ChannelType.THREAD}
            and not directed_to_agent
            and not directed_to_other
            and any(pattern.search(normalized) for pattern in _OPEN_INVITATION_PATTERNS)
        )

        if directed_to_agent:
            ownership = TurnOwnership.AGENT
        elif directed_to_other:
            ownership = TurnOwnership.OTHER
        elif open_invitation:
            ownership = TurnOwnership.OPEN
        else:
            ownership = TurnOwnership.UNCLAIMED

        active_speakers = self._active_speakers(observation, event.actor_id)
        topics = self._topic_terms(content)
        reasons = ["conversation_projection_rebuilt_from_event_log"]
        if is_question:
            reasons.append("current_event_is_question")
        if open_invitation:
            reasons.append("open_group_invitation")
        if directed_to_agent:
            reasons.append("turn_owned_by_agent")
        if directed_to_other:
            reasons.append("turn_owned_by_other")

        return ConversationModel(
            model_version=CONVERSATION_POLICY_VERSION,
            conversation_id=event.conversation_id,
            based_on_state_version=observation.state_version,
            latest_event_id=event.event_id,
            latest_actor_id=event.actor_id,
            active_speaker_ids=active_speakers,
            topic_terms=topics,
            current_event_is_question=is_question,
            open_invitation=open_invitation,
            directed_to_agent=directed_to_agent,
            directed_to_other=directed_to_other,
            turn_ownership=ownership,
            agent_expected_to_respond=directed_to_agent or open_invitation,
            another_participant_better_positioned=directed_to_other,
            reason_codes=tuple(reasons),
            provenance=Provenance(
                kind=ProvenanceKind.RULE,
                source_id=event.event_id,
                method=CONVERSATION_POLICY_VERSION,
                confidence=1.0,
                created_at=event.occurred_at,
            ),
        )

    @staticmethod
    def _active_speakers(
        observation: ObservationSnapshot,
        current_actor_id: str,
    ) -> tuple[str, ...]:
        ordered = [message.actor_id for message in observation.recent_messages[-19:]] + [
            current_actor_id
        ]
        return tuple(dict.fromkeys(reversed(ordered)))[::-1]

    @staticmethod
    def _topic_terms(content: str) -> tuple[str, ...]:
        terms = re.findall(r"[^\W_]{4,}", content.casefold(), flags=re.UNICODE)
        return tuple(dict.fromkeys(term for term in terms if term not in _TOPIC_STOPWORDS))[:8]
