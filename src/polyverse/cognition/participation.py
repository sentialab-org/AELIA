from __future__ import annotations

from polyverse.contracts.events import EventType, InboundEvent
from polyverse.contracts.participation import (
    AttentionLevel,
    AttentionResult,
    ParticipationDecision,
    ParticipationOutcome,
    ProcessingMode,
)
from polyverse.models.conversation import ConversationModel

PARTICIPATION_POLICY_VERSION = "participation-rules-v1"


class ParticipationPolicy:
    def decide(
        self,
        *,
        cycle_id: str,
        event: InboundEvent,
        attention: AttentionResult,
        agent_actor_id: str,
        persona_preference_score: float = 0.0,
        persona_reason_codes: tuple[str, ...] = (),
        internal_dynamics_score: float = 0.0,
        internal_reason_codes: tuple[str, ...] = (),
        conversation: ConversationModel | None = None,
    ) -> ParticipationDecision:
        if not -1.0 <= persona_preference_score <= 1.0:
            raise ValueError("persona_preference_score must be between -1 and 1")
        if not -1.0 <= internal_dynamics_score <= 1.0:
            raise ValueError("internal_dynamics_score must be between -1 and 1")
        base_score = attention.score_breakdown
        combined_internal_score = round(
            max(
                -1.0,
                min(1.0, base_score.internal_dynamics + internal_dynamics_score),
            ),
            6,
        )
        decision_score = type(base_score)(
            direct_mention=base_score.direct_mention,
            direct_message=base_score.direct_message,
            reply_to_agent=base_score.reply_to_agent,
            goal_domain_relevance=base_score.goal_domain_relevance,
            low_value_chatter=base_score.low_value_chatter,
            recent_participation_penalty=base_score.recent_participation_penalty,
            conversation_owned_by_others=base_score.conversation_owned_by_others,
            persona_preference=round(persona_preference_score, 6),
            internal_dynamics=combined_internal_score,
            total=round(
                base_score.total + persona_preference_score + internal_dynamics_score,
                6,
            ),
        )
        addressed = (
            event.channel_type.value == "dm"
            or agent_actor_id in event.mentions
            or (event.reply_to is not None and event.reply_to.actor_id == agent_actor_id)
        )
        if event.event_type is not EventType.MESSAGE_CREATED:
            outcome = ParticipationOutcome.OBSERVE
            decision_reason = "observe_non_message_event"
        elif not event.permissions.can_send_message or not event.permissions.can_reply:
            outcome = ParticipationOutcome.SILENT if addressed else ParticipationOutcome.OBSERVE
            decision_reason = "output_permission_unavailable"
        elif (
            conversation is not None
            and conversation.open_invitation
            and not conversation.another_participant_better_positioned
            and attention.processing_mode is ProcessingMode.FULL
        ):
            outcome = ParticipationOutcome.JOIN
            decision_reason = "open_group_question_join"
        elif decision_score.total >= attention.full_cycle_threshold:
            outcome = ParticipationOutcome.REPLY
            decision_reason = "high_attention_reply"
        elif addressed and decision_score.total >= 0.20:
            outcome = ParticipationOutcome.WAIT
            decision_reason = "addressed_but_below_reply_threshold"
        elif addressed:
            outcome = ParticipationOutcome.SILENT
            decision_reason = "addressed_low_salience_silence"
        else:
            outcome = ParticipationOutcome.OBSERVE
            decision_reason = "ambient_context_observed"

        confidence = self._confidence(
            outcome,
            score=decision_score.total,
            full_cycle_threshold=attention.full_cycle_threshold,
            attention_level=attention.level,
        )
        return ParticipationDecision(
            cycle_id=cycle_id,
            outcome=outcome,
            reason_codes=(
                decision_reason,
                *attention.reason_codes,
                *persona_reason_codes,
                *internal_reason_codes,
            ),
            score_breakdown=decision_score,
            confidence=confidence,
            policy_version=PARTICIPATION_POLICY_VERSION,
        )

    @staticmethod
    def _confidence(
        outcome: ParticipationOutcome,
        *,
        score: float,
        full_cycle_threshold: float,
        attention_level: AttentionLevel,
    ) -> float:
        if outcome in {ParticipationOutcome.REPLY, ParticipationOutcome.JOIN}:
            margin = score - full_cycle_threshold
            return min(0.99, 0.80 + max(0.0, margin))
        if outcome in {ParticipationOutcome.OBSERVE, ParticipationOutcome.SILENT}:
            return 0.9 if attention_level is AttentionLevel.LOW else 0.8
        return 0.75
