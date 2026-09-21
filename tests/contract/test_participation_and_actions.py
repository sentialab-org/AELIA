from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from polyverse.contracts.actions import (
    ActionTarget,
    ActionType,
    ContentPlan,
    OutboundAction,
    RiskClass,
)
from polyverse.contracts.participation import (
    ParticipationDecision,
    ParticipationOutcome,
    ScoreBreakdown,
)


def _score() -> ScoreBreakdown:
    return ScoreBreakdown(
        direct_mention=0.85,
        total=0.85,
    )


def test_participation_decision_round_trips_as_versioned_structured_data() -> None:
    decision = ParticipationDecision(
        cycle_id="cycle-001",
        outcome=ParticipationOutcome.REPLY,
        reason_codes=("high_attention_reply", "direct_mention"),
        score_breakdown=_score(),
        confidence=0.9,
        policy_version="participation-rules-v1",
    )

    restored = ParticipationDecision.model_validate_json(decision.model_dump_json())

    assert restored == decision
    assert restored.score_breakdown.total == 0.85


def test_score_breakdown_rejects_an_incorrect_total() -> None:
    with pytest.raises(ValidationError, match="total does not equal"):
        ScoreBreakdown(
            direct_mention=0.85,
            low_value_chatter=-0.35,
            total=0.85,
        )


def test_outbound_action_rejects_unknown_fields() -> None:
    payload = {
        "schema_version": "2.1.0",
        "action_id": "action-001",
        "cycle_id": "cycle-001",
        "action_type": "reply",
        "target": {
            "conversation_id": "conversation-001",
            "reply_to_event_id": "event-001",
        },
        "content_plan": {
            "intent": "brief reply",
            "constraints": ["brief"],
            "prohibited_traits": ["generic_assistant_voice"],
            "generator": "mock-language-port-v1",
        },
        "permission_scope": "send_message",
        "idempotency_key": "cycle:cycle-001:reply",
        "risk_class": "low",
        "created_at": "2026-07-30T00:00:00Z",
        "unexpected": True,
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        OutboundAction.model_validate(payload)


def test_outbound_action_requires_timezone_aware_created_at() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        OutboundAction(
            schema_version="2.1.0",
            action_id="action-001",
            cycle_id="cycle-001",
            action_type=ActionType.REPLY,
            target=ActionTarget(
                conversation_id="conversation-001",
                reply_to_event_id="event-001",
            ),
            content_plan=ContentPlan(
                intent="brief reply",
                constraints=("brief",),
                prohibited_traits=("generic_assistant_voice",),
                generator="mock-language-port-v1",
            ),
            permission_scope="send_message",
            idempotency_key="cycle:cycle-001:reply",
            risk_class=RiskClass.LOW,
            created_at=datetime(2026, 7, 30),
        )


def test_valid_outbound_action_normalizes_timestamp_to_utc() -> None:
    action = OutboundAction(
        schema_version="2.1.0",
        action_id="action-001",
        cycle_id="cycle-001",
        action_type=ActionType.REPLY,
        target=ActionTarget(
            conversation_id="conversation-001",
            reply_to_event_id="event-001",
        ),
        content_plan=ContentPlan(
            intent="brief reply",
            constraints=("brief",),
            prohibited_traits=("generic_assistant_voice",),
            generator="mock-language-port-v1",
        ),
        permission_scope="send_message",
        idempotency_key="cycle:cycle-001:reply",
        risk_class=RiskClass.LOW,
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
    )

    assert action.created_at.tzinfo is UTC


def test_join_action_round_trips_without_a_reply_target() -> None:
    action = OutboundAction(
        schema_version="2.1.0",
        action_id="action-join-001",
        cycle_id="cycle-join-001",
        action_type=ActionType.JOIN,
        target=ActionTarget(conversation_id="conversation-001"),
        content_plan=ContentPlan(
            intent="join open question",
            constraints=("brief",),
            prohibited_traits=("interrupting",),
            generator="mock-language-port-v1",
        ),
        permission_scope="send_message",
        idempotency_key="event:event-001:join",
        risk_class=RiskClass.LOW,
        created_at=datetime(2026, 7, 30, tzinfo=UTC),
    )

    restored = OutboundAction.model_validate_json(action.model_dump_json())

    assert restored == action
    assert restored.target.reply_to_event_id is None


def test_action_target_semantics_reject_reply_without_target_and_join_with_target() -> None:
    common = {
        "schema_version": "2.1.0",
        "cycle_id": "cycle-001",
        "content_plan": ContentPlan(
            intent="communicate",
            constraints=("brief",),
            prohibited_traits=(),
            generator="mock-language-port-v1",
        ),
        "permission_scope": "send_message",
        "risk_class": RiskClass.LOW,
        "created_at": datetime(2026, 7, 30, tzinfo=UTC),
    }
    with pytest.raises(ValidationError, match="reply action requires"):
        OutboundAction(
            **common,
            action_id="reply-without-target",
            action_type=ActionType.REPLY,
            target=ActionTarget(conversation_id="conversation-001"),
            idempotency_key="reply-without-target",
        )
    with pytest.raises(ValidationError, match="join action cannot"):
        OutboundAction(
            **common,
            action_id="join-with-target",
            action_type=ActionType.JOIN,
            target=ActionTarget(
                conversation_id="conversation-001",
                reply_to_event_id="event-001",
            ),
            idempotency_key="join-with-target",
        )
