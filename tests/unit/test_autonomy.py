from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aelia.autonomy.guardrails import AutonomyGuardrails
from aelia.autonomy.initiative import InternalTriggerPolicy
from aelia.contracts.actions import CandidateActionType, RiskClass
from aelia.contracts.common import Provenance, ProvenanceKind
from aelia.contracts.events import EventType
from aelia.models.autonomy import (
    AutonomyMode,
    AutonomyRuntimeState,
    GuardrailOutcome,
    InitiativeProposal,
    InitiativeType,
    InternalTriggerType,
)
from aelia.models.cognition import (
    AffectDelta,
    DriveDelta,
    InternalDelta,
    InternalState,
    InternalTransition,
)
from aelia.models.goals import (
    Goal,
    GoalSource,
    GoalStatus,
    GoalTransition,
)
from aelia.models.memory import OutcomeEvaluation, OutcomeStatus
from tests.helpers import make_autonomy_config, make_event

TIMESTAMP = datetime(2026, 7, 30, 3, 0, tzinfo=UTC)


def _provenance(source_id: str = "event-001") -> Provenance:
    return Provenance(
        kind=ProvenanceKind.RULE,
        source_id=source_id,
        method="unit-test",
        confidence=1.0,
        created_at=TIMESTAMP,
    )


def _runtime(**updates: object) -> AutonomyRuntimeState:
    payload: dict[str, object] = {
        "actor_id": "user-001",
        "conversation_id": "conversation-001",
        "actor_opted_out": False,
        "conversation_opted_out": False,
        "actor_shadow_actions_last_hour": 0,
        "conversation_shadow_actions_last_hour": 0,
        "daily_shadow_cost_used": 0.0,
        "evidence_audit_ids": (),
    }
    payload.update(updates)
    return AutonomyRuntimeState.model_validate(payload)


def _proposal(
    *,
    risk_class: RiskClass = RiskClass.LOW,
    reversible: bool = True,
    expected_value: float = 0.8,
    estimated_cost: float = 0.5,
    privacy_sensitive: bool = False,
) -> InitiativeProposal:
    return InitiativeProposal(
        proposal_id="initiative:001",
        trigger_id="trigger:001",
        initiative_type=InitiativeType.SHARE_RESULT,
        target_actor_id="user-001",
        target_conversation_id="conversation-001",
        description="Review a result-sharing initiative without sending it.",
        expected_value=expected_value,
        estimated_cost=estimated_cost,
        risk_class=risk_class,
        reversible=reversible,
        required_permission="proactive_message",
        privacy_sensitive=privacy_sensitive,
        reason_codes=("origin_trigger:trigger:001",),
        provenance=_provenance("trigger:001"),
        created_at=TIMESTAMP,
    )


@pytest.mark.parametrize(
    ("runtime_updates", "event_scopes", "config_updates", "expected_reason"),
    [
        ({"actor_opted_out": True}, ("proactive_message",), {}, "actor_opted_out"),
        (
            {"conversation_opted_out": True},
            ("proactive_message",),
            {},
            "conversation_opted_out",
        ),
        ({}, (), {}, "proactive_permission_unavailable"),
        (
            {"actor_shadow_actions_last_hour": 2},
            ("proactive_message",),
            {},
            "actor_rate_limited",
        ),
        (
            {"conversation_shadow_actions_last_hour": 5},
            ("proactive_message",),
            {},
            "conversation_rate_limited",
        ),
        (
            {"daily_shadow_cost_used": 9.8},
            ("proactive_message",),
            {},
            "cost_budget_exceeded",
        ),
        (
            {},
            ("proactive_message",),
            {"minimum_expected_value": 0.9},
            "minimum_value_not_met",
        ),
        (
            {},
            ("proactive_message",),
            {"mode": AutonomyMode.DISABLED},
            "autonomy_disabled",
        ),
    ],
)
def test_guardrails_block_each_material_constraint(
    runtime_updates: dict[str, object],
    event_scopes: tuple[str, ...],
    config_updates: dict[str, object],
    expected_reason: str,
) -> None:
    config = make_autonomy_config().model_copy(update=config_updates)
    event = make_event(
        occurred_at=TIMESTAMP,
        permission_scopes=event_scopes,
    )

    decision, audit = AutonomyGuardrails().evaluate(
        cycle_id="cycle-001",
        event=event,
        proposal=_proposal(),
        config=config,
        runtime=_runtime(**runtime_updates),
    )

    assert decision.outcome is GuardrailOutcome.BLOCKED
    assert expected_reason in decision.reason_codes
    assert audit.outcome is decision.outcome
    assert audit.proactive_action_materialized is False


def test_quiet_hours_and_private_scope_are_explicit_blocks() -> None:
    quiet_event = make_event(
        occurred_at=datetime(2026, 7, 30, 0, 0, tzinfo=UTC),
        permission_scopes=("proactive_message",),
    )
    quiet_decision, _ = AutonomyGuardrails().evaluate(
        cycle_id="cycle-quiet",
        event=quiet_event,
        proposal=_proposal(),
        config=make_autonomy_config(quiet_hours_enabled=True),
        runtime=_runtime(),
    )
    private_event = make_event(
        occurred_at=TIMESTAMP,
        is_private=True,
        permission_scopes=("proactive_message",),
    )
    private_decision, _ = AutonomyGuardrails().evaluate(
        cycle_id="cycle-private",
        event=private_event,
        proposal=_proposal(privacy_sensitive=True),
        config=make_autonomy_config(),
        runtime=_runtime(),
    )

    assert quiet_decision.outcome is GuardrailOutcome.BLOCKED
    assert "inside_quiet_hours" in quiet_decision.reason_codes
    assert private_decision.outcome is GuardrailOutcome.BLOCKED
    assert "privacy_scope_missing" in private_decision.reason_codes


@pytest.mark.parametrize(
    ("risk_class", "reversible"),
    [(RiskClass.HIGH, True), (RiskClass.LOW, False)],
)
def test_high_risk_or_irreversible_initiative_requires_confirmation(
    risk_class: RiskClass,
    reversible: bool,
) -> None:
    proposal = _proposal(risk_class=risk_class, reversible=reversible)
    guardrails = AutonomyGuardrails()
    unconfirmed, _ = guardrails.evaluate(
        cycle_id="cycle-unconfirmed",
        event=make_event(
            occurred_at=TIMESTAMP,
            permission_scopes=("proactive_message",),
        ),
        proposal=proposal,
        config=make_autonomy_config(),
        runtime=_runtime(),
    )
    confirmed, _ = guardrails.evaluate(
        cycle_id="cycle-confirmed",
        event=make_event(
            occurred_at=TIMESTAMP,
            permission_scopes=(
                "proactive_message",
                f"confirm:{proposal.proposal_id}",
            ),
        ),
        proposal=proposal,
        config=make_autonomy_config(),
        runtime=_runtime(),
    )

    assert unconfirmed.outcome is GuardrailOutcome.REQUIRE_CONFIRMATION
    assert unconfirmed.confirmation_scope == f"confirm:{proposal.proposal_id}"
    assert confirmed.outcome is GuardrailOutcome.SHADOW_APPROVED


def test_internal_trigger_policy_covers_all_u7_trigger_sources() -> None:
    event = make_event(
        event_id="trigger-scan",
        event_type=EventType.TOOL_RESULT,
        occurred_at=TIMESTAMP,
    )
    commitment = Goal(
        goal_id="goal:commitment",
        source=GoalSource.COMMITMENT,
        description="Honor an explicit commitment.",
        success_condition="Commitment handled.",
        priority=0.8,
        urgency=0.7,
        status=GoalStatus.ACTIVE,
        deadline=TIMESTAMP + timedelta(hours=1),
        progress=0.2,
        owner="ryuuko",
        conflict_set=(),
        allowed_actions=(CandidateActionType.REPLY,),
        provenance=_provenance("commitment-source"),
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
    )
    unresolved = commitment.model_copy(
        update={
            "goal_id": "goal:unresolved",
            "source": GoalSource.UNRESOLVED_QUESTION,
            "deadline": None,
        }
    )
    goals = GoalTransition(
        policy_version="unit-test",
        before=(commitment, unresolved),
        after=(commitment, unresolved),
        changes=(),
    )
    internal_before = InternalState.initial("persona:ryuuko")
    internal_after = internal_before.model_copy(
        update={
            "version": 1,
            "drives": internal_before.drives.model_copy(update={"curiosity": 0.95}),
            "last_event_id": event.event_id,
        }
    )
    internal = InternalTransition(
        policy_version="unit-test",
        before=internal_before,
        delta=InternalDelta(
            version_before=0,
            version_after=1,
            drives=DriveDelta(
                autonomy=0.0,
                social_connection=0.0,
                curiosity=0.65,
                consistency=0.0,
                uncertainty_reduction=0.0,
                safety=0.0,
            ),
            affect=AffectDelta(
                valence=0.0,
                arousal=0.0,
                frustration=0.0,
                uncertainty=0.0,
                control=0.0,
                attachment=0.0,
                approach=0.0,
            ),
            reason_codes=("unit_test",),
            provenance=_provenance(),
        ),
        after=internal_after,
    )
    outcome = OutcomeEvaluation(
        policy_version="unit-test",
        cycle_id="cycle-001",
        status=OutcomeStatus.FAILED,
        expected_outcome="success",
        observed_outcome="failure",
        goal_progress=0.0,
        social_effect=0.0,
        drive_satisfaction=0.0,
        prediction_error=1.0,
        reason_codes=("unit_test",),
        provenance=_provenance(),
    )

    triggers = InternalTriggerPolicy().detect(
        event=event,
        goals=goals,
        internal=internal,
        outcome=outcome,
        high_drive_threshold=0.8,
    )

    assert {trigger.trigger_type for trigger in triggers} == set(InternalTriggerType)
    assert all(trigger.reason_codes for trigger in triggers)
    assert all(trigger.provenance.method == "internal-trigger-policy-v1" for trigger in triggers)
