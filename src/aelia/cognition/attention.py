from __future__ import annotations

from dataclasses import dataclass

from aelia.contracts.events import ChannelType, EventType, InboundEvent
from aelia.contracts.observation import ObservationSnapshot
from aelia.contracts.participation import (
    AttentionLevel,
    AttentionResult,
    ParticipationOutcome,
    ProcessingMode,
    ScoreBreakdown,
)
from aelia.models.cognition import InternalState
from aelia.models.conversation import ConversationModel

ATTENTION_POLICY_VERSION = "attention-rules-v1"


@dataclass(frozen=True)
class AttentionPolicyConfig:
    direct_mention_score: float = 0.85
    direct_message_score: float = 0.70
    reply_to_agent_score: float = 0.80
    low_value_chatter_score: float = -0.35
    recent_reply_penalty: float = -0.15
    recent_reply_penalty_cap: float = -0.45
    conversation_owned_score: float = -0.65
    medium_threshold: float = 0.20
    full_cycle_threshold: float = 0.65
    recent_participation_window: int = 5


class AttentionPolicy:
    def __init__(self, config: AttentionPolicyConfig | None = None) -> None:
        self.config = config or AttentionPolicyConfig()

    def evaluate(
        self,
        event: InboundEvent,
        observation: ObservationSnapshot,
        conversation: ConversationModel | None = None,
        internal: InternalState | None = None,
    ) -> AttentionResult:
        direct_mention = (
            self.config.direct_mention_score
            if observation.agent_actor_id in event.mentions
            else 0.0
        )
        direct_message = (
            self.config.direct_message_score if event.channel_type is ChannelType.DM else 0.0
        )
        reply_to_agent = (
            self.config.reply_to_agent_score
            if event.reply_to is not None and event.reply_to.actor_id == observation.agent_actor_id
            else 0.0
        )
        low_value_chatter = (
            self.config.low_value_chatter_score if self._is_low_value(event) else 0.0
        )
        recent_replies = sum(
            participation.outcome
            in {
                ParticipationOutcome.REPLY,
                ParticipationOutcome.JOIN,
            }
            for participation in observation.recent_participation[
                -self.config.recent_participation_window :
            ]
        )
        recent_participation_penalty = (
            round(
                max(
                    self.config.recent_reply_penalty * recent_replies,
                    self.config.recent_reply_penalty_cap,
                ),
                6,
            )
            if recent_replies
            else 0.0
        )
        conversation_owned_by_others = (
            self.config.conversation_owned_score
            if (
                conversation.another_participant_better_positioned
                if conversation is not None
                else self._is_owned_by_others(event, observation.agent_actor_id)
            )
            else 0.0
        )
        goal_domain_relevance = (
            0.70
            if conversation is not None
            and conversation.current_event_is_question
            and conversation.open_invitation
            else 0.0
        )
        context_relevant = (
            conversation.agent_expected_to_respond
            if conversation is not None
            else event.channel_type is ChannelType.DM
            or observation.agent_actor_id in event.mentions
            or (
                event.reply_to is not None and event.reply_to.actor_id == observation.agent_actor_id
            )
        )
        internal_dynamics = (
            round(
                max(
                    -0.2,
                    min(
                        0.2,
                        internal.drives.curiosity * 0.08
                        + internal.drives.uncertainty_reduction * 0.06
                        - internal.drives.safety * 0.08
                        - internal.affect.frustration * 0.06,
                    ),
                ),
                6,
            )
            if internal is not None and context_relevant
            else 0.0
        )

        components = {
            "direct_mention": direct_mention,
            "direct_message": direct_message,
            "reply_to_agent": reply_to_agent,
            "goal_domain_relevance": goal_domain_relevance,
            "low_value_chatter": low_value_chatter,
            "recent_participation_penalty": recent_participation_penalty,
            "conversation_owned_by_others": conversation_owned_by_others,
            "internal_dynamics": internal_dynamics,
        }
        score = round(sum(components.values()), 6)
        breakdown = ScoreBreakdown(**components, total=score)

        if score >= self.config.full_cycle_threshold:
            level = AttentionLevel.HIGH
            processing_mode = ProcessingMode.FULL
        elif score >= self.config.medium_threshold:
            level = AttentionLevel.MEDIUM
            processing_mode = ProcessingMode.LIGHTWEIGHT
        else:
            level = AttentionLevel.LOW
            processing_mode = ProcessingMode.LIGHTWEIGHT

        reason_codes: list[str] = []
        if goal_domain_relevance:
            reason_codes.extend(("open_group_question", "agent_relevance_open_invitation"))
        else:
            reason_codes.append("no_goal_domain_relevance_signal")
        if internal_dynamics:
            reason_codes.append("prior_internal_state_modulates_attention")
        reason_codes.extend(
            name
            for name, contribution in components.items()
            if contribution != 0.0 and name != "goal_domain_relevance"
        )
        if event.event_type is not EventType.MESSAGE_CREATED:
            reason_codes.append("non_message_event")

        return AttentionResult(
            policy_version=ATTENTION_POLICY_VERSION,
            level=level,
            processing_mode=processing_mode,
            reason_codes=tuple(reason_codes),
            score_breakdown=breakdown,
            full_cycle_threshold=self.config.full_cycle_threshold,
        )

    @staticmethod
    def _is_low_value(event: InboundEvent) -> bool:
        if event.event_type is not EventType.MESSAGE_CREATED:
            return True
        if event.content is None:
            return True
        normalized = " ".join(event.content.casefold().split())
        if not normalized:
            return True
        chatter = {
            "hi",
            "hey",
            "hello",
            "yo",
            "ừ",
            "ừm",
            "ờ",
            "ok",
            "okay",
            "lol",
            "haha",
            "😂",
            "👍",
        }
        return normalized in chatter

    @staticmethod
    def _is_owned_by_others(event: InboundEvent, agent_actor_id: str) -> bool:
        if event.channel_type is ChannelType.DM:
            return False
        if event.reply_to is not None and event.reply_to.actor_id not in {
            None,
            agent_actor_id,
        }:
            return True
        return bool(event.mentions) and agent_actor_id not in event.mentions
