from __future__ import annotations

from pathlib import Path

import pytest

from aelia.runtime.observability import TraceObservabilityService
from aelia.runtime.replay import ReplayService
from aelia.storage.database import Database
from aelia.storage.repositories import SqliteKernelRepository
from tests.helpers import make_event, make_foundation


@pytest.mark.asyncio
async def test_foundation_cycle_replays_deterministically(tmp_path: Path) -> None:
    repository, orchestrator = await make_foundation(tmp_path)
    processed = await orchestrator.process(make_event())

    replay = await ReplayService(repository).replay_cycle(processed.trace.cycle_id)

    assert replay.matched is True
    assert replay.expected_sha256 == replay.actual_sha256


@pytest.mark.asyncio
async def test_replay_survives_repository_restart(tmp_path: Path) -> None:
    repository, orchestrator = await make_foundation(tmp_path)
    processed = await orchestrator.process(make_event(event_id="restart-event"))

    restarted = SqliteKernelRepository(Database(repository.database.path))
    await restarted.initialize()
    replay = await ReplayService(restarted).replay_cycle(processed.trace.cycle_id)

    assert replay.matched is True
    assert replay.event_id == "restart-event"


@pytest.mark.asyncio
async def test_trace_comparison_reports_exact_paths(tmp_path: Path) -> None:
    repository, orchestrator = await make_foundation(tmp_path)
    left = await orchestrator.process(
        make_event(event_id="compare-left", content="left private content")
    )
    right = await orchestrator.process(
        make_event(event_id="compare-right", content="right private content")
    )
    service = TraceObservabilityService(repository)

    same = await service.compare_cycles(left.trace.cycle_id, left.trace.cycle_id)
    different = await service.compare_cycles(
        left.trace.cycle_id,
        right.trace.cycle_id,
    )

    assert same.exact_match is True
    assert same.differing_paths == ()
    assert different.exact_match is False
    assert different.same_event is False
    assert "$.event_id" in different.differing_paths


@pytest.mark.asyncio
async def test_trace_export_redacts_private_data_by_default(tmp_path: Path) -> None:
    repository, orchestrator = await make_foundation(tmp_path)
    event = make_event(
        event_id="private-event-id",
        actor_id="private-actor-id",
        conversation_id="private-conversation-id",
        content="top secret content",
    )
    processed = await orchestrator.process(event)
    service = TraceObservabilityService(repository)

    redacted = await service.export_cycle(processed.trace.cycle_id)
    unredacted = await service.export_cycle(
        processed.trace.cycle_id,
        redact_private_data=False,
    )
    redacted_json = redacted.model_dump_json()
    unredacted_json = unredacted.model_dump_json()

    assert redacted.private_data_redacted is True
    assert "top secret content" not in redacted_json
    assert "private-actor-id" not in redacted_json
    assert "private-conversation-id" not in redacted_json
    assert "top secret content" in unredacted_json
    assert "private-actor-id" in unredacted_json
