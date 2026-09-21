from __future__ import annotations

from pathlib import Path

import pytest

from aelia.storage.repositories import EventConflictError
from tests.helpers import make_event, make_foundation


@pytest.mark.asyncio
async def test_repeated_event_returns_original_cycle(tmp_path: Path) -> None:
    repository, orchestrator = await make_foundation(tmp_path)
    event = make_event()

    first = await orchestrator.process(event)
    second = await orchestrator.process(event)

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.trace == first.trace
    assert await repository.get_cycle_for_event(event.event_id) == first.trace

    async with repository.database.connection() as connection:
        event_cursor = await connection.execute("SELECT COUNT(*) AS count FROM inbound_events")
        cycle_cursor = await connection.execute("SELECT COUNT(*) AS count FROM cycles")
        event_count = await event_cursor.fetchone()
        cycle_count = await cycle_cursor.fetchone()
    assert event_count is not None
    assert cycle_count is not None
    assert int(event_count["count"]) == 1
    assert int(cycle_count["count"]) == 1


@pytest.mark.asyncio
async def test_reused_event_id_with_new_payload_is_conflict(tmp_path: Path) -> None:
    _, orchestrator = await make_foundation(tmp_path)

    await orchestrator.process(make_event(content="original"))

    with pytest.raises(EventConflictError, match="different payload"):
        await orchestrator.process(make_event(content="changed"))
