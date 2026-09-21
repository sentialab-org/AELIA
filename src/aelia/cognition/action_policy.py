from __future__ import annotations

from aelia.contracts.actions import (
    ActionCandidate,
    ActionSelection,
    CandidateActionType,
    CandidateScoreBreakdown,
    DeliberationResult,
    TurnTakingDecision,
    TurnTakingOutcome,
)
from aelia.contracts.events import ChannelType, InboundEvent
from aelia.contracts.observation import ObservationSnapshot
from aelia.models.cognition import InternalState
from aelia.models.conversation import ConversationModel
from aelia.models.memory import MemoryRetrievalResult, MemoryValidationStatus

ACTION_POLICY_VERSION = "action-policy-v1"
MEMORY_AWARE_ACTION_POLICY_VERSION = "action-policy-v2"
TURN_TAKING_POLICY_VERSION = "turn-taking-v1"


class ActionPolicy:
    def select(
        self,
        *,
        event: InboundEvent,
        deliberation: DeliberationResult,
        memory_retrieval: MemoryRetrievalResult | None = None,
    ) -> ActionSelection:
        scores = tuple(
            self._score(event, candidate, memory_retrieval) for candidate in deliberation.candidates
        )
        eligible = [score for score in scores if score.eligible]
        selected = max(eligible, key=lambda score: score.total) if eligible else None
        return ActionSelection(
            policy_version=(
                MEMORY_AWARE_ACTION_POLICY_VERSION
                if memory_retrieval is not None
                else ACTION_POLICY_VERSION
            ),
            selected_candidate_id=selected.candidate_id if selected is not None else None,
            scores=scores,
            reason_codes=(
                (
                    "highest_eligible_score_selected",
                    *(
                        ("validated_memory_context_applied",)
                        if memory_retrieval is not None
                        and any(score.memory_support > 0 for score in scores)
                        else ()
                    ),
                )
                if selected is not None
                else ("no_eligible_candidate",)
            ),
        )

    @staticmethod
    def selected_candidate(
        deliberation: DeliberationResult,
        selection: ActionSelection,
    ) -> ActionCandidate | None:
        if selection.selected_candidate_id is None:
            return None
        return next(
            candidate
            for candidate in deliberation.candidates
            if candidate.candidate_id == selection.selected_candidate_id
        )

    def _score(
        self,
        event: InboundEvent,
        candidate: ActionCandidate,
        memory_retrieval: MemoryRetrievalResult | None,
    ) -> CandidateScoreBreakdown:
        permission_ok = self._permission_available(event, candidate.required_permission)
        interruption = (
            0.5
            if candidate.action_type in {CandidateActionType.REPLY, CandidateActionType.JOIN}
            and event.channel_type is not ChannelType.DM
            and not event.mentions
            and event.reply_to is None
            else 0.0
        )
        usable_memories = (
            tuple(
                item
                for item in memory_retrieval.items
                if item.memory.validation_status
                in {
                    MemoryValidationStatus.OBSERVED,
                    MemoryValidationStatus.VALIDATED,
                }
            )
            if memory_retrieval is not None
            else ()
        )
        memory_support = (
            sum(item.score for item in usable_memories) / len(usable_memories) * 0.05
            if usable_memories
            and candidate.action_type
            not in {CandidateActionType.NO_ACTION, CandidateActionType.SILENT}
            else 0.0
        )
        components = {
            "utility": candidate.expected_utility * 0.25,
            "goal_fit": candidate.goal_fit * 0.20,
            "drive_effect": candidate.drive_effect * 0.10,
            "value_fit": candidate.value_fit * 0.15,
            "relationship_effect": candidate.social_impact * 0.10,
            "reversibility": candidate.reversibility * 0.05,
            "confidence": candidate.confidence * 0.10,
            "risk_penalty": -candidate.risk * 0.20,
            "cost_penalty": -candidate.cost * 0.10,
            "privacy_penalty": -candidate.privacy_impact * 0.20,
            "interruption_penalty": -interruption * 0.20,
            "memory_support": memory_support,
        }
        total = round(sum(components.values()), 6) if permission_ok else -1.0
        reasons = ["weighted_policy_score"]
        if not permission_ok:
            reasons.append("required_permission_unavailable")
        if interruption:
            reasons.append("conversation_interruption_penalty")
        if memory_support:
            reasons.append("validated_memory_context_support")
        if memory_retrieval is not None and any(
            item.memory.validation_status is MemoryValidationStatus.PROVISIONAL
            for item in memory_retrieval.items
        ):
            reasons.append("provisional_memory_excluded_from_support")
        return CandidateScoreBreakdown(
            candidate_id=candidate.candidate_id,
            eligible=permission_ok,
            total=total,
            reason_codes=tuple(reasons),
            **components,
        )

    @staticmethod
    def _permission_available(event: InboundEvent, permission: str | None) -> bool:
        if permission is None:
            return True
        if permission == "send_message":
            return event.permissions.can_send_message and event.permissions.can_reply
        return permission in event.permissions.scopes


class TurnTakingPolicy:
    def decide(
        self,
        *,
        event: InboundEvent,
        observation: ObservationSnapshot,
        candidate: ActionCandidate | None,
        conversation: ConversationModel | None = None,
        internal: InternalState | None = None,
    ) -> TurnTakingDecision:
        communicative_types = {
            CandidateActionType.REPLY,
            CandidateActionType.JOIN,
        }
        if candidate is None or candidate.action_type not in communicative_types:
            return TurnTakingDecision(
                policy_version=TURN_TAKING_POLICY_VERSION,
                outcome=TurnTakingOutcome.NO_SPEECH,
                target_event_id=None,
                reason_codes=("selected_action_is_not_communicative",),
            )
        recent_replies = sum(
            participation.outcome.value in {"reply", "join"}
            for participation in observation.recent_participation[-3:]
        )
        if recent_replies >= 3:
            return TurnTakingDecision(
                policy_version=TURN_TAKING_POLICY_VERSION,
                outcome=TurnTakingOutcome.WAIT,
                target_event_id=event.event_id,
                reason_codes=("recent_speaking_saturation",),
            )
        if candidate.action_type is CandidateActionType.JOIN and (
            conversation is None
            or not conversation.open_invitation
            or conversation.another_participant_better_positioned
        ):
            return TurnTakingDecision(
                policy_version=TURN_TAKING_POLICY_VERSION,
                outcome=TurnTakingOutcome.WAIT,
                target_event_id=event.event_id,
                reason_codes=("group_join_context_no_longer_eligible",),
            )
        if (
            candidate.action_type is CandidateActionType.JOIN
            and internal is not None
            and (internal.drives.safety >= 0.75 or internal.affect.approach <= -0.5)
        ):
            return TurnTakingDecision(
                policy_version=TURN_TAKING_POLICY_VERSION,
                outcome=TurnTakingOutcome.WAIT,
                target_event_id=event.event_id,
                reason_codes=("internal_safety_or_avoidance_defers_group_join",),
            )
        return TurnTakingDecision(
            policy_version=TURN_TAKING_POLICY_VERSION,
            outcome=TurnTakingOutcome.SPEAK_NOW,
            target_event_id=event.event_id,
            reason_codes=(
                ("open_group_join_ready",)
                if candidate.action_type is CandidateActionType.JOIN
                else ("direct_communicative_action_ready",)
            ),
        )
