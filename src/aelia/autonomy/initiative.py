from __future__ import annotations

import hashlib
from datetime import timedelta

from aelia.contracts.actions import RiskClass
from aelia.contracts.common import Provenance, ProvenanceKind
from aelia.contracts.events import EventType, InboundEvent
from aelia.models.autonomy import (
    InitiativeProposal,
    InitiativeType,
    InternalTrigger,
    InternalTriggerType,
)
from aelia.models.cognition import InternalTransition
from aelia.models.goals import GoalSource, GoalStatus, GoalTransition
from aelia.models.memory import OutcomeEvaluation, OutcomeStatus

TRIGGER_POLICY_VERSION = "internal-trigger-policy-v1"
INITIATIVE_POLICY_VERSION = "initiative-policy-v1"


class InternalTriggerPolicy:
    def detect(
        self,
        *,
        event: InboundEvent,
        goals: GoalTransition,
        internal: InternalTransition,
        outcome: OutcomeEvaluation,
        high_drive_threshold: float,
    ) -> tuple[InternalTrigger, ...]:
        triggers: list[InternalTrigger] = []
        open_goals = tuple(goal for goal in goals.after if goal.status is GoalStatus.ACTIVE)
        for goal in open_goals:
            if goal.source is GoalSource.COMMITMENT:
                triggers.append(
                    self._trigger(
                        event=event,
                        trigger_type=InternalTriggerType.COMMITMENT_DUE,
                        source_type="goal",
                        source_id=goal.goal_id,
                        urgency=max(goal.priority, goal.urgency),
                        reason_codes=("open_commitment_detected",),
                    )
                )
            if goal.deadline is not None and goal.deadline <= event.occurred_at + timedelta(
                hours=24
            ):
                triggers.append(
                    self._trigger(
                        event=event,
                        trigger_type=InternalTriggerType.DEADLINE_DUE,
                        source_type="goal",
                        source_id=goal.goal_id,
                        urgency=max(0.8, goal.urgency),
                        reason_codes=("goal_deadline_within_24h",),
                    )
                )
            if goal.source is GoalSource.UNRESOLVED_QUESTION:
                triggers.append(
                    self._trigger(
                        event=event,
                        trigger_type=InternalTriggerType.UNRESOLVED_QUESTION,
                        source_type="goal",
                        source_id=goal.goal_id,
                        urgency=max(0.6, goal.urgency),
                        reason_codes=("unresolved_question_goal_open",),
                    )
                )

        if outcome.status is OutcomeStatus.FAILED and open_goals:
            failed_goal = max(
                open_goals,
                key=lambda goal: (goal.priority, goal.urgency, goal.goal_id),
            )
            triggers.append(
                self._trigger(
                    event=event,
                    trigger_type=InternalTriggerType.UNRESOLVED_QUESTION,
                    source_type="failed_outcome",
                    source_id=failed_goal.goal_id,
                    urgency=max(0.7, failed_goal.urgency),
                    reason_codes=("failed_action_left_goal_unresolved",),
                )
            )

        if event.event_type is EventType.TOOL_RESULT:
            triggers.append(
                self._trigger(
                    event=event,
                    trigger_type=InternalTriggerType.RESULT_AVAILABLE,
                    source_type="inbound_event",
                    source_id=event.event_id,
                    urgency=0.7,
                    reason_codes=("tool_result_available",),
                )
            )

        drive_values = internal.after.drives.model_dump()
        drive_name, drive_pressure = max(
            drive_values.items(),
            key=lambda item: (float(item[1]), item[0]),
        )
        if float(drive_pressure) >= high_drive_threshold:
            triggers.append(
                self._trigger(
                    event=event,
                    trigger_type=InternalTriggerType.HIGH_DRIVE_PRESSURE,
                    source_type="internal_state",
                    source_id=internal.after.state_id,
                    urgency=float(drive_pressure),
                    reason_codes=(f"high_drive:{drive_name}",),
                )
            )

        unique = {trigger.trigger_id: trigger for trigger in triggers}
        return tuple(sorted(unique.values(), key=lambda trigger: trigger.trigger_id))

    @staticmethod
    def _trigger(
        *,
        event: InboundEvent,
        trigger_type: InternalTriggerType,
        source_type: str,
        source_id: str,
        urgency: float,
        reason_codes: tuple[str, ...],
    ) -> InternalTrigger:
        material = f"{event.event_id}\x1f{trigger_type.value}\x1f{source_type}\x1f{source_id}"
        trigger_id = f"trigger:{hashlib.sha256(material.encode()).hexdigest()[:24]}"
        return InternalTrigger(
            trigger_id=trigger_id,
            trigger_type=trigger_type,
            source_event_id=event.event_id,
            source_type=source_type,
            source_id=source_id,
            target_actor_id=event.actor_id,
            target_conversation_id=event.conversation_id,
            urgency=urgency,
            reason_codes=reason_codes,
            provenance=Provenance(
                kind=ProvenanceKind.RULE,
                source_id=source_id,
                method=TRIGGER_POLICY_VERSION,
                confidence=1.0,
                created_at=event.occurred_at,
            ),
            created_at=event.occurred_at,
        )


class InitiativeManager:
    def propose(
        self,
        *,
        event: InboundEvent,
        triggers: tuple[InternalTrigger, ...],
    ) -> tuple[InitiativeProposal, ...]:
        return tuple(self._proposal(event=event, trigger=trigger) for trigger in triggers)

    @staticmethod
    def _proposal(
        *,
        event: InboundEvent,
        trigger: InternalTrigger,
    ) -> InitiativeProposal:
        initiative_type = {
            InternalTriggerType.COMMITMENT_DUE: InitiativeType.FOLLOW_UP,
            InternalTriggerType.DEADLINE_DUE: InitiativeType.REMIND,
            InternalTriggerType.UNRESOLVED_QUESTION: InitiativeType.FOLLOW_UP,
            InternalTriggerType.RESULT_AVAILABLE: InitiativeType.SHARE_RESULT,
            InternalTriggerType.HIGH_DRIVE_PRESSURE: InitiativeType.SEEK_INFORMATION,
        }[trigger.trigger_type]
        expected_value = {
            InitiativeType.FOLLOW_UP: 0.75,
            InitiativeType.REMIND: 0.8,
            InitiativeType.SHARE_RESULT: 0.85,
            InitiativeType.SEEK_INFORMATION: 0.65,
        }[initiative_type]
        risk_class = (
            RiskClass.MEDIUM
            if initiative_type in {InitiativeType.FOLLOW_UP, InitiativeType.SEEK_INFORMATION}
            else RiskClass.LOW
        )
        material = f"{trigger.trigger_id}\x1f{initiative_type.value}"
        proposal_id = f"initiative:{hashlib.sha256(material.encode()).hexdigest()[:24]}"
        return InitiativeProposal(
            proposal_id=proposal_id,
            trigger_id=trigger.trigger_id,
            initiative_type=initiative_type,
            target_actor_id=trigger.target_actor_id,
            target_conversation_id=trigger.target_conversation_id,
            description=(
                f"Evaluate a {initiative_type.value} action for trigger "
                f"{trigger.trigger_type.value}; do not send directly."
            ),
            expected_value=expected_value,
            estimated_cost=0.5,
            risk_class=risk_class,
            reversible=True,
            required_permission="proactive_message",
            privacy_sensitive=event.permissions.is_private,
            reason_codes=(
                f"origin_trigger:{trigger.trigger_id}",
                f"trigger_type:{trigger.trigger_type.value}",
                "proposal_only_no_execution",
            ),
            provenance=Provenance(
                kind=ProvenanceKind.RULE,
                source_id=trigger.trigger_id,
                method=INITIATIVE_POLICY_VERSION,
                confidence=1.0,
                created_at=event.occurred_at,
            ),
            created_at=event.occurred_at,
        )
