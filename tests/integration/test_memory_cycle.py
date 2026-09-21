from __future__ import annotations

from pathlib import Path

from polyverse.contracts.events import ChannelType
from polyverse.models.goals import GoalStatus
from polyverse.models.memory import (
    LearningTarget,
    MemoryCategory,
    MemoryValidationStatus,
    OutcomeStatus,
    ProposalStatus,
    ReflectionTriggerType,
)
from polyverse.runtime.orchestrator import (
    MEMORY_ORCHESTRATOR_VERSION,
    MemoryOrchestrator,
)
from polyverse.runtime.ports import FailingExecutionPort
from polyverse.runtime.replay import ReplayService
from polyverse.storage.database import Database
from polyverse.storage.repositories import SqliteKernelRepository
from tests.helpers import make_event, make_memory


async def test_memory_cycle_persists_references_and_retrieves_all_categories(
    tmp_path: Path,
) -> None:
    repository, orchestrator = await make_memory(tmp_path)
    first = await orchestrator.process(
        make_event(
            event_id="memory-self-report",
            content="I am 19 years old",
            channel_type=ChannelType.DM,
            mentions=("agent-001",),
        )
    )

    assert first.trace.orchestrator_version == MEMORY_ORCHESTRATOR_VERSION
    assert first.trace.memory_write_set is not None
    written_categories = {record.category for record in first.trace.memory_write_set.records}
    assert written_categories == {
        MemoryCategory.EPISODIC,
        MemoryCategory.SEMANTIC,
        MemoryCategory.SOCIAL,
        MemoryCategory.AUTOBIOGRAPHICAL,
        MemoryCategory.PROCEDURAL,
        MemoryCategory.COMMITMENT,
    }
    semantic = next(
        record
        for record in first.trace.memory_write_set.records
        if record.category is MemoryCategory.SEMANTIC
    )
    assert semantic.validation_status is MemoryValidationStatus.PROVISIONAL
    assert semantic.canonical_source_type == "belief"
    assert semantic.summary == "Canonical belief reference."

    second = await orchestrator.process(
        make_event(
            event_id="memory-retrieval",
            content="can you remember this?",
            channel_type=ChannelType.DM,
            mentions=("agent-001",),
        )
    )

    assert second.trace.memory_retrieval is not None
    assert second.trace.memory_retrieval.vector_index_used is False
    assert {item.memory.category for item in second.trace.memory_retrieval.items} == set(
        MemoryCategory
    )
    assert all(item.reason_codes for item in second.trace.memory_retrieval.items)
    assert all(
        item.provenance.source_id == item.memory.memory_id
        for item in second.trace.memory_retrieval.items
    )
    assert second.trace.action_selection is not None
    assert second.trace.action_selection.policy_version == "action-policy-v2"
    assert any(score.memory_support > 0 for score in second.trace.action_selection.scores)
    assert any(
        "provisional_memory_excluded_from_support" in score.reason_codes
        for score in second.trace.action_selection.scores
    )

    async with repository.database.connection() as connection:
        cursor = await connection.execute(
            "SELECT category, record_json FROM memory_records ORDER BY category"
        )
        rows = tuple(await cursor.fetchall())
    assert MemoryCategory.WORKING.value not in {str(row["category"]) for row in rows}
    assert all("19 years old" not in str(row["record_json"]) for row in rows)


async def test_duplicate_event_cannot_duplicate_memory_or_outcome(tmp_path: Path) -> None:
    repository, orchestrator = await make_memory(tmp_path)
    event = make_event(
        event_id="memory-idempotent",
        content="can you help?",
        mentions=("agent-001",),
    )

    first = await orchestrator.process(event)
    duplicate = await orchestrator.process(event)

    assert duplicate.duplicate is True
    assert duplicate.trace == first.trace
    async with repository.database.connection() as connection:
        memory_cursor = await connection.execute(
            "SELECT memory_id, source_event_ids_json FROM memory_records"
        )
        memory_rows = tuple(await memory_cursor.fetchall())
        outcome_cursor = await connection.execute("SELECT count(*) FROM cycle_outcomes")
        outcome_count = await outcome_cursor.fetchone()
    assert outcome_count is not None
    assert int(outcome_count[0]) == 1
    assert memory_rows
    assert all(str(row["source_event_ids_json"]).count(event.event_id) <= 1 for row in memory_rows)
    assert any(str(row["source_event_ids_json"]).count(event.event_id) == 1 for row in memory_rows)


async def test_repository_restart_preserves_and_retrieves_canonical_memory(
    tmp_path: Path,
) -> None:
    repository, orchestrator = await make_memory(tmp_path)
    await orchestrator.process(
        make_event(
            event_id="memory-before-restart",
            content="I am 19 years old",
            channel_type=ChannelType.DM,
            mentions=("agent-001",),
        )
    )

    restarted_repository = SqliteKernelRepository(Database(repository.database.path))
    restarted = MemoryOrchestrator(
        restarted_repository,
        agent_actor_id="agent-001",
        persona_specification=orchestrator.persona_specification,
    )
    await restarted.initialize()
    result = await restarted.process(
        make_event(
            event_id="memory-after-restart",
            content="do you recall the context?",
            channel_type=ChannelType.DM,
            mentions=("agent-001",),
        )
    )

    assert result.trace.memory_retrieval is not None
    assert any(
        item.memory.canonical_source_id == "memory-before-restart"
        for item in result.trace.memory_retrieval.items
    )
    replay = await ReplayService(
        restarted_repository,
        persona_specification=restarted.persona_specification,
    ).replay_cycle(result.trace.cycle_id)
    assert replay.matched is True


async def test_failed_execution_creates_only_validation_gated_learning(
    tmp_path: Path,
) -> None:
    repository, orchestrator = await make_memory(
        tmp_path,
        execution_port=FailingExecutionPort(),
    )
    result = await orchestrator.process(
        make_event(
            event_id="memory-failed-execution",
            content="can you check this?",
            mentions=("agent-001",),
        )
    )

    assert result.trace.outcome_evaluation is not None
    assert result.trace.outcome_evaluation.status is OutcomeStatus.FAILED
    assert result.trace.outcome_evaluation.goal_progress == 0.0
    assert result.trace.goal_transition is not None
    assert result.trace.goal_transition.after[-1].status is GoalStatus.ACTIVE
    assert {proposal.target for proposal in result.trace.learning_proposals} == {
        LearningTarget.STRATEGY,
        LearningTarget.RETRIEVAL_WEIGHT,
    }
    assert all(
        proposal.status is ProposalStatus.PENDING_VALIDATION and proposal.requires_validation
        for proposal in result.trace.learning_proposals
    )
    assert all(
        "internal_affect_modulates_learning_strength" in proposal.reason_codes
        for proposal in result.trace.learning_proposals
    )
    assert {trigger.trigger_type for trigger in result.trace.reflection_triggers} == {
        ReflectionTriggerType.EXECUTION_FAILURE
    }

    async with repository.database.connection() as connection:
        proposal_cursor = await connection.execute(
            "SELECT status, requires_validation FROM learning_proposals"
        )
        proposals = tuple(await proposal_cursor.fetchall())
        trigger_cursor = await connection.execute(
            "SELECT trigger_type, requires_validation FROM reflection_triggers"
        )
        triggers = tuple(await trigger_cursor.fetchall())
    assert len(proposals) == 2
    assert all(
        str(row["status"]) == ProposalStatus.PENDING_VALIDATION.value
        and int(row["requires_validation"]) == 1
        for row in proposals
    )
    assert len(triggers) == 1
    assert str(triggers[0]["trigger_type"]) == ReflectionTriggerType.EXECUTION_FAILURE.value
    assert int(triggers[0]["requires_validation"]) == 1


async def test_belief_conflict_and_boundary_change_create_review_proposals(
    tmp_path: Path,
) -> None:
    _, orchestrator = await make_memory(tmp_path)
    await orchestrator.process(
        make_event(
            event_id="memory-age-19",
            content="I am 19 years old",
            channel_type=ChannelType.DM,
            mentions=("agent-001",),
        )
    )
    conflict = await orchestrator.process(
        make_event(
            event_id="memory-age-20",
            content="I am 20 years old",
            channel_type=ChannelType.DM,
            mentions=("agent-001",),
        )
    )
    boundary = await orchestrator.process(
        make_event(
            event_id="memory-boundary",
            content="where exactly is your dorm room?",
            channel_type=ChannelType.DM,
            mentions=("agent-001",),
        )
    )

    assert LearningTarget.BELIEF in {
        proposal.target for proposal in conflict.trace.learning_proposals
    }
    assert ReflectionTriggerType.BELIEF_CONFLICT in {
        trigger.trigger_type for trigger in conflict.trace.reflection_triggers
    }
    assert LearningTarget.RELATIONSHIP in {
        proposal.target for proposal in boundary.trace.learning_proposals
    }
    assert ReflectionTriggerType.RELATIONSHIP_CHANGE in {
        trigger.trigger_type for trigger in boundary.trace.reflection_triggers
    }
