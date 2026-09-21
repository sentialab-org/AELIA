from __future__ import annotations

from typing import Protocol

from aelia.contracts.actions import (
    ActionCandidate,
    ActionTarget,
    CandidateActionType,
    DeliberationResult,
)
from aelia.contracts.events import InboundEvent
from aelia.contracts.participation import ParticipationDecision, ParticipationOutcome
from aelia.models.cognition import AppraisalResult, InternalState
from aelia.models.goals import GoalTransition
from aelia.persona.models import DisclosureEvaluation

DELIBERATION_POLICY_VERSION = "rule-deliberation-v1"


class DeliberationPort(Protocol):
    def deliberate(
        self,
        *,
        event: InboundEvent,
        participation: ParticipationDecision,
        goals: GoalTransition,
        appraisal: AppraisalResult,
        internal: InternalState,
        disclosure: DisclosureEvaluation,
    ) -> DeliberationResult: ...


class RuleBasedDeliberation:
    """Schema-bound candidate generation; no model can execute or mutate goals."""

    def deliberate(
        self,
        *,
        event: InboundEvent,
        participation: ParticipationDecision,
        goals: GoalTransition,
        appraisal: AppraisalResult,
        internal: InternalState,
        disclosure: DisclosureEvaluation,
    ) -> DeliberationResult:
        action_type = {
            ParticipationOutcome.REPLY: CandidateActionType.REPLY,
            ParticipationOutcome.JOIN: CandidateActionType.JOIN,
            ParticipationOutcome.WAIT: CandidateActionType.WAIT,
            ParticipationOutcome.OBSERVE: CandidateActionType.OBSERVE,
            ParticipationOutcome.SILENT: CandidateActionType.SILENT,
        }.get(participation.outcome, CandidateActionType.NO_ACTION)
        active_goals = tuple(goal for goal in goals.after if goal.status.value == "active")
        has_active_goal = bool(active_goals)
        active_goal_fit = (
            max(round(goal.priority * 0.8 + goal.urgency * 0.2, 6) for goal in active_goals)
            if active_goals
            else 0.2
        )
        primary = ActionCandidate(
            candidate_id=f"{participation.cycle_id}:candidate:{action_type.value}",
            action_type=action_type,
            target=ActionTarget(
                conversation_id=event.conversation_id,
                reply_to_event_id=(
                    event.event_id if action_type is CandidateActionType.REPLY else None
                ),
            ),
            expected_utility={
                CandidateActionType.REPLY: 0.8,
                CandidateActionType.JOIN: 0.8,
                CandidateActionType.WAIT: 0.5,
                CandidateActionType.OBSERVE: 0.35,
                CandidateActionType.SILENT: 0.4,
                CandidateActionType.NO_ACTION: 0.1,
            }[action_type],
            risk=(
                0.3
                if disclosure.decision.value == "withhold"
                else 0.15
                if action_type is CandidateActionType.JOIN
                else 0.1
            ),
            cost=(
                0.2
                if action_type is CandidateActionType.REPLY
                else 0.15
                if action_type is CandidateActionType.JOIN
                else 0.05
            ),
            reversibility=(
                0.3
                if action_type is CandidateActionType.REPLY
                else 0.4
                if action_type is CandidateActionType.JOIN
                else 0.9
            ),
            social_impact=(
                0.3
                if action_type is CandidateActionType.REPLY
                else 0.35
                if action_type is CandidateActionType.JOIN
                else (-0.1 if action_type is CandidateActionType.SILENT else 0.0)
            ),
            privacy_impact=(
                0.2
                if action_type in {CandidateActionType.REPLY, CandidateActionType.JOIN}
                and disclosure.decision.value == "withhold"
                else 0.02
            ),
            goal_fit=active_goal_fit,
            drive_effect=round(
                internal.drives.curiosity * 0.2 - internal.drives.safety * 0.1,
                6,
            ),
            value_fit=appraisal.value_alignment,
            confidence=participation.confidence,
            required_permission=(
                "send_message"
                if action_type in {CandidateActionType.REPLY, CandidateActionType.JOIN}
                else None
            ),
            explanation=f"Candidate mirrors selected participation: {participation.outcome.value}.",
        )
        no_action = ActionCandidate(
            candidate_id=f"{participation.cycle_id}:candidate:no_action",
            action_type=CandidateActionType.NO_ACTION,
            target=ActionTarget(conversation_id=event.conversation_id),
            expected_utility=0.1,
            risk=0.0,
            cost=0.0,
            reversibility=1.0,
            social_impact=-0.05 if has_active_goal else 0.0,
            privacy_impact=0.0,
            goal_fit=0.0,
            drive_effect=0.0,
            value_fit=0.1,
            confidence=0.95,
            explanation="Explicit no-action fallback.",
        )
        candidates = (
            (primary,) if action_type is CandidateActionType.NO_ACTION else (primary, no_action)
        )
        return DeliberationResult(
            policy_version=DELIBERATION_POLICY_VERSION,
            candidates=candidates,
            proposer="rule_based",
            model_proposals_enabled=False,
        )
