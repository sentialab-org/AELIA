from __future__ import annotations

from pathlib import Path

from polyverse.cognition.appraisal import AppraisalPolicy
from polyverse.cognition.attention import AttentionPolicy
from polyverse.cognition.dynamics import (
    InternalDynamicsPolicy,
    InternalParticipationPolicy,
)
from polyverse.cognition.memory import LearningPolicy
from polyverse.cognition.participation import ParticipationPolicy
from polyverse.cognition.perception import PerceptionPolicy
from polyverse.cognition.social import SocialPolicy
from polyverse.contracts.events import InboundEvent
from polyverse.contracts.observation import ObservationSnapshot
from polyverse.contracts.participation import AttentionResult
from polyverse.models.cognition import AppraisalResult, InternalState, InternalTransition
from polyverse.models.perception import PerceptionResult
from polyverse.models.social import SocialState, SocialTransition
from polyverse.persona.disclosure import DisclosureGate
from polyverse.persona.loader import PersonaSourceLoader
from polyverse.persona.models import PersonaView
from polyverse.persona.participation import PersonaParticipationPolicy
from polyverse.persona.selector import PersonaViewSelector
from tests.helpers import make_event

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _pipeline(
    event: InboundEvent,
    social_before: SocialState,
    internal_before: InternalState,
) -> tuple[
    AttentionResult,
    PerceptionResult,
    SocialTransition,
    PersonaView,
    AppraisalResult,
    InternalTransition,
]:
    specification = PersonaSourceLoader(
        PROJECT_ROOT / "src/polyverse/persona/source/manifest.json",
        repository_root=PROJECT_ROOT,
    ).load_specification()
    observation = ObservationSnapshot(
        conversation_id=event.conversation_id,
        agent_actor_id="agent-001",
        state_version=0,
    )
    attention = AttentionPolicy().evaluate(event, observation)
    perception = PerceptionPolicy().perceive(event=event, attention=attention)
    social = SocialPolicy().transition(event, social_before)
    disclosure = DisclosureGate().evaluate(
        content=event.content,
        relationship_tier=social_before.tier,
    )
    view = PersonaViewSelector().select(
        event=event,
        specification=specification,
        relationship_tier=social_before.tier,
        disclosure=disclosure,
    )
    appraisal = AppraisalPolicy().appraise(
        event=event,
        observation=observation,
        perception=perception,
        social=social.after,
        persona_view=view,
        disclosure=disclosure,
    )
    internal = InternalDynamicsPolicy().transition(
        event=event,
        before=internal_before,
        perception=perception,
        appraisal=appraisal,
        social=social,
    )
    return attention, perception, social, view, appraisal, internal


def test_boundary_appraisal_updates_drive_and_affect_before_participation() -> None:
    event = make_event(
        event_id="boundary-appraisal",
        content="where exactly is your dorm room?",
        mentions=("agent-001",),
    )
    initial_social = SocialState.unknown(event.platform, event.actor_id)
    initial_internal = InternalState.initial("persona:ryuuko")

    attention, _, _, view, appraisal, internal = _pipeline(
        event,
        initial_social,
        initial_internal,
    )
    persona_influence = PersonaParticipationPolicy().evaluate(view)
    internal_influence = InternalParticipationPolicy().evaluate(internal.after)
    decision = ParticipationPolicy().decide(
        cycle_id="cycle-boundary",
        event=event,
        attention=attention,
        agent_actor_id="agent-001",
        persona_preference_score=persona_influence.score,
        persona_reason_codes=persona_influence.reason_codes,
        internal_dynamics_score=internal_influence.score,
        internal_reason_codes=internal_influence.reason_codes,
    )

    assert appraisal.value_alignment == -0.8
    assert internal.after.drives.autonomy > initial_internal.drives.autonomy
    assert internal.after.drives.safety > initial_internal.drives.safety
    assert internal.after.affect.valence < 0.0
    assert internal.after.affect.frustration > 0.0
    assert decision.score_breakdown.internal_dynamics == internal_influence.score
    assert "affect_modulates_participation" in decision.reason_codes


def test_one_apology_cannot_reset_negative_affect() -> None:
    boundary = make_event(
        event_id="boundary-first",
        content="where exactly is your dorm room?",
        mentions=("agent-001",),
    )
    social_initial = SocialState.unknown(boundary.platform, boundary.actor_id)
    internal_initial = InternalState.initial("persona:ryuuko")
    _, _, boundary_social, _, _, boundary_internal = _pipeline(
        boundary,
        social_initial,
        internal_initial,
    )
    apology = make_event(
        event_id="apology-second",
        content="sorry, my bad",
        mentions=("agent-001",),
    )
    _, _, _, _, _, apology_internal = _pipeline(
        apology,
        boundary_social.after,
        boundary_internal.after,
    )

    assert boundary_internal.after.affect.valence < 0.0
    assert apology_internal.after.affect.valence < 0.0
    assert apology_internal.after.affect.frustration > 0.0
    assert "affect_inertia_applied" in apology_internal.delta.reason_codes


def test_affect_causally_modulates_learning_strength() -> None:
    neutral = make_event(
        event_id="learning-neutral",
        content="hello",
        mentions=("agent-001",),
    )
    boundary = make_event(
        event_id="learning-boundary",
        content="where exactly is your dorm room?",
        mentions=("agent-001",),
    )
    social = SocialState.unknown(neutral.platform, neutral.actor_id)
    internal = InternalState.initial("persona:ryuuko")

    *_, neutral_internal = _pipeline(neutral, social, internal)
    *_, boundary_internal = _pipeline(boundary, social, internal)

    neutral_strength = LearningPolicy.learning_strength(neutral_internal)
    boundary_strength = LearningPolicy.learning_strength(boundary_internal)

    assert boundary_internal.after.affect.frustration > neutral_internal.after.affect.frustration
    assert boundary_strength > neutral_strength
