from __future__ import annotations

from pathlib import Path

import pytest

from aelia.contracts.actions import (
    ActionType,
    CandidateActionType,
    ExecutionStatus,
    OutboundAction,
    TurnTakingOutcome,
)
from aelia.contracts.events import InboundEvent, ReplyReference
from aelia.contracts.participation import ParticipationDecision, ParticipationOutcome
from aelia.contracts.traces import CycleStatus, CycleTrace
from aelia.models.goals import GoalStatus
from aelia.runtime.ports import FailingExecutionPort
from aelia.runtime.replay import ReplayService
from aelia.storage.repositories import (
    ConcurrentStateError,
    FoundationIngestResult,
    canonical_json,
    sha256_text,
)
from tests.helpers import make_action, make_event


async def test_action_cycle_scores_selects_generates_executes_and_replays(
    tmp_path: Path,
) -> None:
    repository, orchestrator = await make_action(tmp_path)
    event = make_event(
        event_id="action-reply-001",
        content="can you help with this code?",
        mentions=("agent-001",),
    )

    result = await orchestrator.process(event)

    assert isinstance(result.trace.decision, ParticipationDecision)
    assert result.trace.decision.outcome is ParticipationOutcome.REPLY
    assert result.trace.goal_transition is not None
    assert result.trace.goal_transition.after[-1].status is GoalStatus.COMPLETED
    assert result.trace.deliberation is not None
    assert result.trace.deliberation.model_proposals_enabled is False
    reply_candidate = next(
        candidate
        for candidate in result.trace.deliberation.candidates
        if candidate.action_type is CandidateActionType.REPLY
    )
    resolved_goal = result.trace.goal_transition.after[-1]
    assert reply_candidate.goal_fit == round(
        resolved_goal.priority * 0.8 + resolved_goal.urgency * 0.2,
        6,
    )
    assert result.trace.action_selection is not None
    assert len(result.trace.action_selection.scores) >= 2
    assert result.trace.action_selection.selected_candidate_id is not None
    reply_score = next(
        score
        for score in result.trace.action_selection.scores
        if score.candidate_id == reply_candidate.candidate_id
    )
    assert reply_score.goal_fit == reply_candidate.goal_fit * 0.2
    assert result.trace.turn_taking is not None
    assert result.trace.turn_taking.outcome is TurnTakingOutcome.SPEAK_NOW
    assert result.trace.selected_action is not None
    assert result.trace.selected_action.schema_version == "2.2.0"
    assert result.trace.selected_action.idempotency_key == f"event:{event.event_id}:reply"
    assert result.trace.selected_action.content_plan.prompt is not None
    assert result.trace.selected_action.content_plan.prompt.owner == "aelia-language-boundary"
    assert result.trace.language_generation is not None
    assert result.trace.language_generation.changed_participation is False
    assert result.trace.execution_result is not None
    assert result.trace.execution_result.status is ExecutionStatus.SIMULATED

    replay = await ReplayService(
        repository,
        persona_specification=orchestrator.persona_specification,
    ).replay_cycle(result.trace.cycle_id)
    assert replay.matched is True


async def test_permission_denial_selects_non_communicative_action(tmp_path: Path) -> None:
    repository, orchestrator = await make_action(tmp_path)
    event = make_event(
        event_id="action-permission-denied",
        content="answer this",
        mentions=("agent-001",),
        can_reply=False,
    )

    result = await orchestrator.process(event)

    assert isinstance(result.trace.decision, ParticipationDecision)
    assert result.trace.decision.outcome is ParticipationOutcome.SILENT
    assert result.trace.deliberation is not None
    assert result.trace.action_selection is not None
    selected = next(
        candidate
        for candidate in result.trace.deliberation.candidates
        if candidate.candidate_id == result.trace.action_selection.selected_candidate_id
    )
    assert selected.action_type in {
        CandidateActionType.SILENT,
        CandidateActionType.NO_ACTION,
    }
    assert result.trace.selected_action is None
    assert result.trace.execution_result is None
    async with repository.database.connection() as connection:
        cursor = await connection.execute("SELECT count(*) FROM outbound_actions")
        row = await cursor.fetchone()
    assert row is not None
    assert int(row[0]) == 0


async def test_failed_execution_is_structured_persisted_and_replayable(
    tmp_path: Path,
) -> None:
    repository, orchestrator = await make_action(
        tmp_path,
        execution_port=FailingExecutionPort(),
    )
    event = make_event(
        event_id="action-failure-001",
        content="can you check this?",
        mentions=("agent-001",),
    )

    result = await orchestrator.process(event)

    assert result.trace.execution_result is not None
    assert result.trace.execution_result.status is ExecutionStatus.FAILED
    assert result.trace.execution_result.error_code == "simulated_execution_failure"
    assert result.trace.execution_result.side_effect_performed is False
    assert result.trace.execution_result.retryable is True
    assert result.trace.status is CycleStatus.FAILED
    assert len(result.trace.errors) == 1
    assert result.trace.errors[0].code == "simulated_execution_failure"
    assert result.trace.errors[0].retryable is True
    async with repository.database.connection() as connection:
        cursor = await connection.execute(
            "SELECT execution_status, execution_json FROM outbound_actions"
        )
        row = await cursor.fetchone()
    assert row is not None
    assert str(row["execution_status"]) == "failed"
    assert "simulated_execution_failure" in str(row["execution_json"])

    replay = await ReplayService(
        repository,
        persona_specification=orchestrator.persona_specification,
    ).replay_cycle(result.trace.cycle_id)
    assert replay.matched is True


async def test_duplicate_event_creates_only_one_outbound_action(tmp_path: Path) -> None:
    repository, orchestrator = await make_action(tmp_path)
    event = make_event(
        event_id="action-idempotent-001",
        content="can you review this?",
        mentions=("agent-001",),
    )

    first = await orchestrator.process(event)
    duplicate = await orchestrator.process(event)
    async with repository.database.connection() as connection:
        cursor = await connection.execute("SELECT action_id, idempotency_key FROM outbound_actions")
        rows = tuple(await cursor.fetchall())

    assert duplicate.duplicate is True
    assert duplicate.trace == first.trace
    assert len(rows) == 1
    assert str(rows[0]["idempotency_key"]) == f"event:{event.event_id}:reply"


async def test_recovered_state_conflict_is_persisted_in_retry_history_and_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, orchestrator = await make_action(tmp_path)
    original_store = repository.store_observation_cycle
    store_attempts = 0

    async def conflict_once(
        event: InboundEvent,
        trace: CycleTrace,
    ) -> FoundationIngestResult:
        nonlocal store_attempts
        store_attempts += 1
        if store_attempts == 1:
            raise ConcurrentStateError("simulated optimistic commit conflict")
        return await original_store(event, trace)

    monkeypatch.setattr(repository, "store_observation_cycle", conflict_once)
    result = await orchestrator.process(
        make_event(
            event_id="action-retry-history-001",
            content="can you review this?",
            mentions=("agent-001",),
        )
    )

    assert store_attempts == 2
    assert len(result.trace.retries) == 1
    assert result.trace.retries[0].attempt == 1
    assert result.trace.retries[0].component == "state_commit"
    assert result.trace.retries[0].code == "concurrent_state_conflict"

    replay = await ReplayService(
        repository,
        persona_specification=orchestrator.persona_specification,
    ).replay_cycle(result.trace.cycle_id)
    assert replay.matched is True


async def test_replay_remains_compatible_with_action_and_trace_2_1(
    tmp_path: Path,
) -> None:
    repository, orchestrator = await make_action(tmp_path)
    result = await orchestrator.process(
        make_event(
            event_id="legacy-action-replay-001",
            content="can you review this?",
            mentions=("agent-001",),
        )
    )
    assert result.trace.selected_action is not None
    legacy_plan = result.trace.selected_action.content_plan.model_copy(update={"prompt": None})
    legacy_action = OutboundAction.model_validate(
        {
            **result.trace.selected_action.model_dump(mode="python"),
            "schema_version": "2.1.0",
            "content_plan": legacy_plan,
        }
    )
    legacy_trace = CycleTrace.model_validate(
        {
            **result.trace.model_dump(mode="python"),
            "schema_version": "2.1.0",
            "selected_action": legacy_action,
            "retries": (),
        }
    )
    legacy_json = canonical_json(legacy_trace.model_dump(mode="json"))
    async with repository.database.connection() as connection:
        await connection.execute(
            """
            UPDATE cycles
            SET schema_version = ?, trace_json = ?, trace_sha256 = ?
            WHERE cycle_id = ?
            """,
            (
                legacy_trace.schema_version,
                legacy_json,
                sha256_text(legacy_json),
                legacy_trace.cycle_id,
            ),
        )
        await connection.commit()

    replay = await ReplayService(
        repository,
        persona_specification=orchestrator.persona_specification,
    ).replay_cycle(legacy_trace.cycle_id)

    assert replay.matched is True


async def test_open_group_question_can_be_joined_without_a_direct_mention(
    tmp_path: Path,
) -> None:
    repository, orchestrator = await make_action(tmp_path)
    event = make_event(
        event_id="group-open-question-001",
        content="Mọi người có ai biết cách sửa lỗi này không?",
    )

    result = await orchestrator.process(event)

    assert result.trace.conversation_model is not None
    assert result.trace.conversation_model.open_invitation is True
    assert result.trace.decision.outcome is ParticipationOutcome.JOIN
    assert result.trace.selected_action is not None
    assert result.trace.selected_action.action_type is ActionType.JOIN
    assert result.trace.selected_action.target.reply_to_event_id is None
    assert result.trace.execution_result is not None
    assert result.trace.execution_result.status is ExecutionStatus.SIMULATED
    assert result.trace.execution_result.side_effect_performed is False

    replay = await ReplayService(
        repository,
        persona_specification=orchestrator.persona_specification,
    ).replay_cycle(result.trace.cycle_id)
    assert replay.matched is True


async def test_question_owned_by_another_participant_is_not_joined(
    tmp_path: Path,
) -> None:
    _, orchestrator = await make_action(tmp_path)
    event = make_event(
        event_id="group-other-owned-001",
        content="Có ai biết cách sửa không?",
        reply_to=ReplyReference(event_id="other-message", actor_id="other-user"),
    )

    result = await orchestrator.process(event)

    assert result.trace.conversation_model is not None
    assert result.trace.conversation_model.another_participant_better_positioned is True
    assert result.trace.decision.outcome is ParticipationOutcome.OBSERVE
    assert result.trace.selected_action is None


async def test_recent_group_join_prevents_immediate_repeat_participation(
    tmp_path: Path,
) -> None:
    _, orchestrator = await make_action(tmp_path)

    first = await orchestrator.process(
        make_event(
            event_id="group-join-first",
            content="Mọi người có ai biết cách sửa lỗi đầu tiên không?",
        )
    )
    second = await orchestrator.process(
        make_event(
            event_id="group-join-second",
            content="Mọi người có ai biết cách sửa lỗi thứ hai không?",
        )
    )

    assert first.trace.decision.outcome is ParticipationOutcome.JOIN
    assert second.trace.attention is not None
    assert second.trace.attention.score_breakdown.recent_participation_penalty < 0.0
    assert second.trace.decision.outcome is ParticipationOutcome.OBSERVE
    assert second.trace.selected_action is None
