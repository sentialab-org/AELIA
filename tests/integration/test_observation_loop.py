from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aelia.contracts.events import ReplyReference
from aelia.contracts.participation import ParticipationDecision, ParticipationOutcome
from aelia.runtime.orchestrator import ObservationOrchestrator
from aelia.runtime.ports import MockExecutionPort, MockLanguagePort
from aelia.runtime.replay import ReplayService
from aelia.storage.repositories import ConcurrentStateError
from tests.helpers import make_event, make_observation


async def test_ambient_group_stream_uses_lightweight_cycles_and_bounded_buffer(
    tmp_path: Path,
) -> None:
    repository, orchestrator = await make_observation(
        tmp_path,
        conversation_buffer_limit=100,
    )

    full_cycles = 0
    for index in range(100):
        result = await orchestrator.process(
            make_event(
                event_id=f"group-{index:03d}",
                content=f"ambient group message {index}",
            )
        )
        assert isinstance(result.trace.decision, ParticipationDecision)
        assert result.trace.attention is not None
        assert result.trace.decision.outcome is ParticipationOutcome.OBSERVE
        assert result.trace.selected_action is None
        full_cycles += int(result.trace.attention.processing_mode.value == "full")

    snapshot = await repository.load_observation_snapshot("conversation-001", "agent-001")

    assert full_cycles == 0
    assert snapshot.state_version == 100
    assert len(snapshot.recent_messages) == 100
    assert snapshot.recent_messages[0].event_id == "group-000"
    assert snapshot.recent_messages[-1].event_id == "group-099"


async def test_direct_mention_is_prioritized_and_mock_execution_has_no_side_effect(
    tmp_path: Path,
) -> None:
    repository, orchestrator = await make_observation(tmp_path)
    event = make_event(
        event_id="mention-001",
        content="can you check this code?",
        mentions=("agent-001",),
    )

    result = await orchestrator.process(event)

    assert isinstance(result.trace.decision, ParticipationDecision)
    assert result.trace.decision.outcome is ParticipationOutcome.REPLY
    assert result.trace.attention is not None
    assert result.trace.attention.processing_mode.value == "full"
    assert result.trace.selected_action is not None
    assert result.trace.execution_result is not None
    assert result.trace.execution_result.side_effect_performed is False
    assert result.trace.selected_action.target.reply_to_event_id == event.event_id

    replay = await ReplayService(repository).replay_cycle(result.trace.cycle_id)
    assert replay.matched is True


async def test_nonmention_updates_context_without_output(tmp_path: Path) -> None:
    repository, orchestrator = await make_observation(tmp_path)

    result = await orchestrator.process(
        make_event(event_id="ambient-001", content="we changed the deploy time")
    )
    snapshot = await repository.load_observation_snapshot("conversation-001", "agent-001")

    assert isinstance(result.trace.decision, ParticipationDecision)
    assert result.trace.decision.outcome is ParticipationOutcome.OBSERVE
    assert result.trace.selected_action is None
    assert snapshot.state_version == 1
    assert snapshot.recent_messages[-1].event_id == "ambient-001"


async def test_silence_is_a_persisted_policy_result(tmp_path: Path) -> None:
    repository, orchestrator = await make_observation(tmp_path)

    result = await orchestrator.process(
        make_event(
            event_id="no-permission-001",
            content="answer me",
            mentions=("agent-001",),
            can_reply=False,
        )
    )
    stored = await repository.get_cycle(result.trace.cycle_id)

    assert isinstance(stored.decision, ParticipationDecision)
    assert stored.decision.outcome is ParticipationOutcome.SILENT
    assert "output_permission_unavailable" in stored.decision.reason_codes
    assert stored.selected_action is None


async def test_recent_participation_can_produce_wait(tmp_path: Path) -> None:
    _, orchestrator = await make_observation(tmp_path)
    first = await orchestrator.process(
        make_event(event_id="direct-001", content="first direct question", mentions=("agent-001",))
    )
    second = await orchestrator.process(
        make_event(event_id="direct-002", content="second direct question", mentions=("agent-001",))
    )
    third = await orchestrator.process(
        make_event(event_id="direct-003", content="third direct question", mentions=("agent-001",))
    )

    assert isinstance(first.trace.decision, ParticipationDecision)
    assert isinstance(second.trace.decision, ParticipationDecision)
    assert isinstance(third.trace.decision, ParticipationDecision)
    assert first.trace.decision.outcome is ParticipationOutcome.REPLY
    assert second.trace.decision.outcome is ParticipationOutcome.REPLY
    assert third.trace.decision.outcome is ParticipationOutcome.WAIT
    assert third.trace.selected_action is None


async def test_reply_graph_and_duplicate_idempotency(tmp_path: Path) -> None:
    repository, orchestrator = await make_observation(tmp_path)
    event = make_event(
        event_id="reply-001",
        content="answering someone else",
        reply_to=ReplyReference(event_id="parent-001", actor_id="other-user"),
    )

    original = await orchestrator.process(event)
    duplicate = await orchestrator.process(event)

    assert duplicate.duplicate is True
    assert duplicate.trace == original.trace
    async with repository.database.connection() as connection:
        edge_cursor = await connection.execute(
            "SELECT reply_to_event_id, reply_to_actor_id FROM reply_graph_edges"
        )
        edges = tuple(await edge_cursor.fetchall())
        event_cursor = await connection.execute("SELECT count(*) FROM inbound_events")
        event_count_row = await event_cursor.fetchone()

    assert event_count_row is not None
    event_count = int(event_count_row[0])
    assert len(edges) == 1
    edge = next(iter(edges))
    assert str(edge["reply_to_event_id"]) == "parent-001"
    assert str(edge["reply_to_actor_id"]) == "other-user"
    assert event_count == 1


async def test_conversation_buffer_is_pruned_without_resetting_state_version(
    tmp_path: Path,
) -> None:
    repository, orchestrator = await make_observation(
        tmp_path,
        conversation_buffer_limit=3,
    )
    for index in range(5):
        await orchestrator.process(
            make_event(event_id=f"bounded-{index}", content=f"message {index}")
        )

    snapshot = await repository.load_observation_snapshot("conversation-001", "agent-001")

    assert snapshot.state_version == 5
    assert [message.event_id for message in snapshot.recent_messages] == [
        "bounded-2",
        "bounded-3",
        "bounded-4",
    ]


async def test_optimistic_state_version_rejects_stale_cycle(tmp_path: Path) -> None:
    repository, _ = await make_observation(tmp_path)
    snapshot = await repository.load_observation_snapshot("conversation-001", "agent-001")
    timestamp = datetime(2026, 7, 30, tzinfo=UTC)
    first_event = make_event(event_id="race-001", content="first")
    stale_event = make_event(event_id="race-002", content="stale")
    first_trace = ObservationOrchestrator.transition(
        event=first_event,
        observation=snapshot,
        cycle_id="cycle-race-001",
        started_at=timestamp,
        completed_at=timestamp,
        language_port=MockLanguagePort(),
        execution_port=MockExecutionPort(),
    )
    stale_trace = ObservationOrchestrator.transition(
        event=stale_event,
        observation=snapshot,
        cycle_id="cycle-race-002",
        started_at=timestamp,
        completed_at=timestamp,
        language_port=MockLanguagePort(),
        execution_port=MockExecutionPort(),
    )

    await repository.store_observation_cycle(first_event, first_trace)
    with pytest.raises(ConcurrentStateError, match="changed from version 0 to 1"):
        await repository.store_observation_cycle(stale_event, stale_trace)


async def test_migrations_are_idempotent(tmp_path: Path) -> None:
    repository, _ = await make_observation(tmp_path)

    await repository.initialize()
    async with repository.database.connection() as connection:
        cursor = await connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        )
        rows = tuple(await cursor.fetchall())

    assert [(int(row["version"]), str(row["name"])) for row in rows] == [
        (1, "foundation_event_log_and_cycles"),
        (2, "observation_buffer_reply_graph_and_participation"),
        (3, "canonical_social_relationship_state"),
        (4, "beliefs_and_internal_cognitive_state"),
        (5, "goals_and_idempotent_outbound_actions"),
        (6, "canonical_memory_outcomes_and_learning_proposals"),
        (7, "initiative_guardrails_opt_outs_and_audit"),
        (8, "adapter_ingress_and_transactional_dispatch_outbox"),
    ]
