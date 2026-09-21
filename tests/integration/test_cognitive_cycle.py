from __future__ import annotations

from pathlib import Path

from polyverse.contracts.events import ChannelType
from polyverse.models.belief import BeliefStatus
from polyverse.models.perception import EpistemicKind, PerceptionDepth
from polyverse.models.world import WorldStatementKind
from polyverse.runtime.replay import ReplayService
from tests.helpers import make_cognitive, make_event


async def test_cognitive_cycle_persists_belief_internal_state_and_replays(
    tmp_path: Path,
) -> None:
    repository, orchestrator = await make_cognitive(tmp_path)
    event = make_event(
        event_id="cognitive-self-report",
        content="I am 19 years old",
        channel_type=ChannelType.DM,
    )

    result = await orchestrator.process(event)
    belief_snapshot = await repository.load_belief_snapshot(event.platform, event.actor_id)
    internal = await repository.load_internal_state(orchestrator.internal_state_id)

    assert result.trace.perception is not None
    assert result.trace.belief_transition is not None
    assert result.trace.appraisal is not None
    assert result.trace.internal_transition is not None
    assert result.trace.world_model is not None
    assert result.trace.perception.depth is PerceptionDepth.DEEP
    assert result.trace.perception.claim_candidates[0].kind is EpistemicKind.HYPOTHESIS
    assert len(belief_snapshot.records) == 1
    assert belief_snapshot.records[0].status is BeliefStatus.PROVISIONAL
    assert belief_snapshot.records[0].evidence[0].event_id == event.event_id
    assert internal.version == 1
    assert internal.last_event_id == event.event_id
    assert result.trace.world_model.rebuildable is True
    assert {statement.kind for statement in result.trace.world_model.statements} >= {
        WorldStatementKind.HYPOTHESIS,
        WorldStatementKind.BELIEF_REFERENCE,
        WorldStatementKind.CAPABILITY,
        WorldStatementKind.PREDICTION,
    }
    assert result.trace.appraisal is not None
    assert "world_capabilities_informed_controllability" in result.trace.appraisal.reason_codes

    replay = await ReplayService(
        repository,
        persona_specification=orchestrator.persona_specification,
    ).replay_cycle(result.trace.cycle_id)
    assert replay.matched is True


async def test_low_salience_event_stays_observation_without_belief(tmp_path: Path) -> None:
    repository, orchestrator = await make_cognitive(tmp_path)
    event = make_event(event_id="ambient-cognitive", content="ambient group update")

    result = await orchestrator.process(event)
    beliefs = await repository.load_belief_snapshot(event.platform, event.actor_id)

    assert result.trace.perception is not None
    assert result.trace.perception.depth is PerceptionDepth.LIGHTWEIGHT
    assert result.trace.perception.claim_candidates == ()
    assert beliefs.records == ()


async def test_conflicting_reports_are_persisted_as_contested_beliefs(
    tmp_path: Path,
) -> None:
    repository, orchestrator = await make_cognitive(tmp_path)
    await orchestrator.process(
        make_event(
            event_id="report-age-19",
            content="I am 19 years old",
            channel_type=ChannelType.DM,
        )
    )
    await orchestrator.process(
        make_event(
            event_id="report-age-20",
            content="I am 20 years old",
            channel_type=ChannelType.DM,
        )
    )

    beliefs = await repository.load_belief_snapshot(
        make_event().platform,
        make_event().actor_id,
    )

    assert len(beliefs.records) == 2
    assert {belief.status for belief in beliefs.records} == {BeliefStatus.CONTESTED}
    assert all(belief.contradiction_links for belief in beliefs.records)


async def test_duplicate_does_not_repeat_belief_or_internal_update(tmp_path: Path) -> None:
    repository, orchestrator = await make_cognitive(tmp_path)
    event = make_event(
        event_id="cognitive-duplicate",
        content="I am 19 years old",
        channel_type=ChannelType.DM,
    )

    original = await orchestrator.process(event)
    duplicate = await orchestrator.process(event)
    beliefs = await repository.load_belief_snapshot(event.platform, event.actor_id)
    internal = await repository.load_internal_state(orchestrator.internal_state_id)

    assert duplicate.duplicate is True
    assert duplicate.trace == original.trace
    assert len(beliefs.records) == 1
    assert len(beliefs.records[0].evidence) == 1
    assert internal.version == 1
