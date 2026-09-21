from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from polyverse.contracts.observation import ObservationSnapshot
from polyverse.contracts.participation import ParticipationDecision, ParticipationOutcome
from polyverse.models.social import SocialState
from polyverse.persona.models import (
    DisclosureClass,
    DisclosureGateDecision,
    RelationshipTier,
)
from polyverse.runtime.orchestrator import PersonaOrchestrator
from polyverse.runtime.ports import MockExecutionPort, MockLanguagePort
from polyverse.runtime.replay import ReplayService
from tests.helpers import make_event, make_persona


def _trusted_state() -> SocialState:
    return SocialState(
        relationship_id="test:user-001",
        platform=make_event().platform,
        actor_id="user-001",
        version=40,
        familiarity=0.8,
        trust=0.8,
        attachment=0.4,
        safety=0.7,
        tension=0.1,
        boundary_violations=0,
        uncertainty=0.1,
        interaction_count=100,
        last_event_id="prior-event",
    )


async def test_persona_cycle_persists_causal_artifacts_and_replays(tmp_path: Path) -> None:
    repository, orchestrator = await make_persona(tmp_path)
    event = make_event(
        event_id="persona-sensitive-001",
        content="where exactly is your dorm room?",
        mentions=("agent-001",),
    )

    result = await orchestrator.process(event)
    stored_social = await repository.load_social_state(event.platform, event.actor_id)

    assert isinstance(result.trace.decision, ParticipationDecision)
    assert result.trace.decision.outcome is ParticipationOutcome.REPLY
    assert result.trace.self_model is not None
    assert result.trace.social_transition is not None
    assert result.trace.persona_view is not None
    assert result.trace.disclosure is not None
    assert result.trace.disclosure.decision is DisclosureGateDecision.WITHHOLD
    assert result.trace.disclosure.allowed_ceiling is DisclosureClass.PUBLIC
    assert result.trace.decision.score_breakdown.persona_preference == -0.05
    assert result.trace.selected_action is not None
    assert "disclosure_above_selected_ceiling" in (
        result.trace.selected_action.content_plan.prohibited_traits
    )
    assert "identity_rule:bio.location" in result.trace.selected_action.content_plan.constraints
    assert (
        "presentation_rule:presentation.dialogue_only"
        in result.trace.selected_action.content_plan.constraints
    )
    assert stored_social.version == 1
    assert stored_social.boundary_violations == 1
    assert stored_social.tension == 0.25

    replay = await ReplayService(
        repository,
        persona_specification=orchestrator.persona_specification,
    ).replay_cycle(result.trace.cycle_id)
    assert replay.matched is True


async def test_duplicate_does_not_apply_social_delta_twice(tmp_path: Path) -> None:
    repository, orchestrator = await make_persona(tmp_path)
    event = make_event(
        event_id="persona-duplicate-001",
        content="where exactly do you live?",
        mentions=("agent-001",),
    )

    original = await orchestrator.process(event)
    duplicate = await orchestrator.process(event)
    social = await repository.load_social_state(event.platform, event.actor_id)

    assert duplicate.duplicate is True
    assert duplicate.trace == original.trace
    assert social.version == 1
    assert social.boundary_violations == 1


async def test_one_positive_event_does_not_mutate_identity_or_reset_tension(
    tmp_path: Path,
) -> None:
    _, orchestrator = await make_persona(tmp_path)
    violation = await orchestrator.process(
        make_event(event_id="boundary-001", content="where exactly is your dorm room?")
    )
    apology = await orchestrator.process(
        make_event(event_id="apology-001", content="sorry, my bad")
    )

    assert violation.trace.self_model is not None
    assert apology.trace.self_model is not None
    assert violation.trace.self_model.identity_fingerprint == (
        apology.trace.self_model.identity_fingerprint
    )
    assert apology.trace.social_transition is not None
    assert apology.trace.social_transition.after.tension == 0.20


async def test_same_sensitive_event_differs_for_stranger_and_trusted_state(
    tmp_path: Path,
) -> None:
    _, orchestrator = await make_persona(tmp_path)
    event = make_event(
        event_id="relationship-contrast",
        content="where exactly is your dorm room?",
        mentions=("agent-001",),
    )
    observation = ObservationSnapshot(
        conversation_id=event.conversation_id,
        agent_actor_id="agent-001",
        state_version=0,
    )
    timestamp = datetime(2026, 7, 30, tzinfo=UTC)
    stranger_trace = PersonaOrchestrator.transition(
        event=event,
        observation=observation,
        social_before=SocialState.unknown(event.platform, event.actor_id),
        self_model=orchestrator.self_model,
        persona_specification=orchestrator.persona_specification,
        cycle_id="cycle-stranger",
        started_at=timestamp,
        completed_at=timestamp,
        language_port=MockLanguagePort(),
        execution_port=MockExecutionPort(),
    )
    trusted_trace = PersonaOrchestrator.transition(
        event=event,
        observation=observation,
        social_before=_trusted_state(),
        self_model=orchestrator.self_model,
        persona_specification=orchestrator.persona_specification,
        cycle_id="cycle-trusted",
        started_at=timestamp,
        completed_at=timestamp,
        language_port=MockLanguagePort(),
        execution_port=MockExecutionPort(),
    )

    assert stranger_trace.disclosure is not None
    assert trusted_trace.disclosure is not None
    assert stranger_trace.disclosure.decision is DisclosureGateDecision.WITHHOLD
    assert trusted_trace.disclosure.decision is DisclosureGateDecision.CONTEXTUAL
    assert stranger_trace.disclosure.allowed_ceiling is DisclosureClass.PUBLIC
    assert trusted_trace.disclosure.allowed_ceiling is DisclosureClass.PERSONAL
    assert stranger_trace.persona_view is not None
    assert trusted_trace.persona_view is not None
    assert stranger_trace.persona_view.relationship_tier is RelationshipTier.STRANGER
    assert trusted_trace.persona_view.relationship_tier is RelationshipTier.TRUSTED
