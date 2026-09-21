from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from polyverse.contracts.events import EventType
from polyverse.models.autonomy import (
    GuardrailOutcome,
    InitiativeType,
    InternalTriggerType,
    OptOutScope,
)
from polyverse.runtime.orchestrator import AUTONOMY_ORCHESTRATOR_VERSION
from polyverse.runtime.replay import ReplayService
from tests.helpers import (
    make_autonomy,
    make_autonomy_config,
    make_event,
)


async def test_tool_result_creates_audited_shadow_initiative_without_action(
    tmp_path: Path,
) -> None:
    repository, orchestrator = await make_autonomy(tmp_path)
    event = make_event(
        event_id="autonomy-result-ready",
        event_type=EventType.TOOL_RESULT,
        content="The requested build result is ready.",
        permission_scopes=("proactive_message",),
    )

    result = await orchestrator.process(event)

    assert result.trace.orchestrator_version == AUTONOMY_ORCHESTRATOR_VERSION
    autonomy = result.trace.autonomy_evaluation
    assert autonomy is not None
    assert [trigger.trigger_type for trigger in autonomy.triggers] == [
        InternalTriggerType.RESULT_AVAILABLE
    ]
    assert [proposal.initiative_type for proposal in autonomy.proposals] == [
        InitiativeType.SHARE_RESULT
    ]
    assert autonomy.proposals[0].trigger_id == autonomy.triggers[0].trigger_id
    assert "origin_trigger:" in autonomy.proposals[0].reason_codes[0]
    assert autonomy.decisions[0].outcome is GuardrailOutcome.SHADOW_APPROVED
    assert autonomy.proactive_action_materialized is False

    async with repository.database.connection() as connection:
        counts = {}
        for table in (
            "internal_triggers",
            "initiative_proposals",
            "guardrail_decisions",
            "autonomy_audit_log",
            "outbound_actions",
        ):
            cursor = await connection.execute(f"SELECT count(*) FROM {table}")
            row = await cursor.fetchone()
            assert row is not None
            counts[table] = int(row[0])
    assert counts == {
        "internal_triggers": 1,
        "initiative_proposals": 1,
        "guardrail_decisions": 1,
        "autonomy_audit_log": 1,
        "outbound_actions": 0,
    }
    replay = await ReplayService(
        repository,
        persona_specification=orchestrator.persona_specification,
    ).replay_cycle(result.trace.cycle_id)
    assert replay.matched is True


@pytest.mark.parametrize(
    "scope_type",
    [OptOutScope.ACTOR, OptOutScope.CONVERSATION],
)
async def test_persisted_opt_out_blocks_initiative_but_keeps_audit(
    tmp_path: Path,
    scope_type: OptOutScope,
) -> None:
    repository, orchestrator = await make_autonomy(tmp_path)
    scope_id = "user-001" if scope_type is OptOutScope.ACTOR else "conversation-001"
    event = make_event(
        event_id=f"autonomy-opt-out-{scope_type.value}",
        event_type=EventType.TOOL_RESULT,
        content="Result ready.",
        permission_scopes=("proactive_message",),
    )
    await repository.set_autonomy_opt_out(
        scope_type=scope_type,
        scope_id=scope_id,
        opted_out=True,
        source="integration-test",
        updated_at=event.occurred_at,
    )

    result = await orchestrator.process(event)

    autonomy = result.trace.autonomy_evaluation
    assert autonomy is not None
    assert autonomy.decisions[0].outcome is GuardrailOutcome.BLOCKED
    assert f"{scope_type.value}_opted_out" in autonomy.decisions[0].reason_codes
    assert autonomy.audit_records[0].outcome is GuardrailOutcome.BLOCKED
    assert autonomy.audit_records[0].proactive_action_materialized is False


async def test_shadow_rate_limit_is_persistent_across_cycles(tmp_path: Path) -> None:
    repository, orchestrator = await make_autonomy(
        tmp_path,
        autonomy_config=make_autonomy_config(
            actor_limit_per_hour=1,
            conversation_limit_per_hour=10,
        ),
    )
    event_time = make_event().occurred_at
    first = await orchestrator.process(
        make_event(
            event_id="autonomy-rate-1",
            event_type=EventType.TOOL_RESULT,
            content="First result.",
            permission_scopes=("proactive_message",),
        )
    )
    second = await orchestrator.process(
        make_event(
            event_id="autonomy-rate-2",
            event_type=EventType.TOOL_RESULT,
            content="Second result.",
            permission_scopes=("proactive_message",),
        )
    )

    assert first.trace.autonomy_evaluation is not None
    assert second.trace.autonomy_evaluation is not None
    assert first.trace.autonomy_evaluation.decisions[0].outcome is GuardrailOutcome.SHADOW_APPROVED
    second_decision = second.trace.autonomy_evaluation.decisions[0]
    assert second_decision.outcome is GuardrailOutcome.BLOCKED
    assert "actor_rate_limited" in second_decision.reason_codes
    assert second.trace.autonomy_evaluation.runtime_state.actor_shadow_actions_last_hour == 1

    restarted_state = await repository.load_autonomy_runtime_state(
        actor_id="user-001",
        conversation_id="conversation-001",
        hour_window_start=event_time - timedelta(hours=1),
        day_window_start=event_time - timedelta(days=1),
    )
    assert restarted_state.actor_shadow_actions_last_hour == 1


async def test_daily_cost_budget_is_global_across_conversations(tmp_path: Path) -> None:
    _, orchestrator = await make_autonomy(
        tmp_path,
        autonomy_config=make_autonomy_config(
            actor_limit_per_hour=10,
            conversation_limit_per_hour=10,
            daily_cost_budget=0.5,
        ),
    )
    first = await orchestrator.process(
        make_event(
            event_id="autonomy-budget-1",
            actor_id="user-001",
            conversation_id="conversation-001",
            event_type=EventType.TOOL_RESULT,
            content="First result.",
            permission_scopes=("proactive_message",),
        )
    )
    second = await orchestrator.process(
        make_event(
            event_id="autonomy-budget-2",
            actor_id="user-002",
            conversation_id="conversation-002",
            event_type=EventType.TOOL_RESULT,
            content="Second result.",
            permission_scopes=("proactive_message",),
        )
    )

    assert first.trace.autonomy_evaluation is not None
    assert second.trace.autonomy_evaluation is not None
    assert first.trace.autonomy_evaluation.decisions[0].outcome is GuardrailOutcome.SHADOW_APPROVED
    assert second.trace.autonomy_evaluation.runtime_state.daily_shadow_cost_used == 0.5
    assert second.trace.autonomy_evaluation.decisions[0].outcome is GuardrailOutcome.BLOCKED
    assert "cost_budget_exceeded" in second.trace.autonomy_evaluation.decisions[0].reason_codes


async def test_duplicate_event_cannot_duplicate_autonomy_audit(tmp_path: Path) -> None:
    repository, orchestrator = await make_autonomy(tmp_path)
    event = make_event(
        event_id="autonomy-idempotent",
        event_type=EventType.TOOL_RESULT,
        content="Result ready.",
        permission_scopes=("proactive_message",),
    )

    first = await orchestrator.process(event)
    duplicate = await orchestrator.process(event)

    assert duplicate.duplicate is True
    assert duplicate.trace == first.trace
    async with repository.database.connection() as connection:
        cursor = await connection.execute("SELECT count(*) FROM autonomy_audit_log")
        row = await cursor.fetchone()
    assert row is not None
    assert int(row[0]) == 1
