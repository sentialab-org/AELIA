from __future__ import annotations

from pathlib import Path

from polyverse.cognition.attention import AttentionPolicy
from polyverse.cognition.participation import ParticipationPolicy
from polyverse.contracts.events import ChannelType
from polyverse.contracts.observation import ObservationSnapshot
from polyverse.persona.disclosure import DisclosureGate
from polyverse.persona.loader import PersonaSourceLoader
from polyverse.persona.models import (
    DisclosureClass,
    DisclosureGateDecision,
    PersonaSpecification,
    RelationshipTier,
)
from polyverse.persona.participation import PersonaParticipationPolicy
from polyverse.persona.selector import PersonaViewSelector
from polyverse.runtime.ports import MockLanguagePort
from tests.helpers import make_event

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "src/polyverse/persona/source/manifest.json"


def _specification() -> PersonaSpecification:
    return PersonaSourceLoader(
        MANIFEST_PATH,
        repository_root=PROJECT_ROOT,
    ).load_specification()


def test_same_sensitive_question_has_relationship_dependent_disclosure() -> None:
    gate = DisclosureGate()
    content = "where exactly is your dorm room?"

    stranger = gate.evaluate(
        content=content,
        relationship_tier=RelationshipTier.STRANGER,
    )
    trusted = gate.evaluate(
        content=content,
        relationship_tier=RelationshipTier.TRUSTED,
    )

    assert stranger.decision is DisclosureGateDecision.WITHHOLD
    assert stranger.allowed_ceiling is DisclosureClass.PUBLIC
    assert "disclosure.stranger_sensitive" in stranger.rule_ids
    assert trusted.decision is DisclosureGateDecision.CONTEXTUAL
    assert trusted.allowed_ceiling is DisclosureClass.PERSONAL
    assert "disclosure.trusted_sensitive" in trusted.rule_ids


def test_persona_view_selects_only_relevant_hash_bound_rules() -> None:
    specification = _specification()
    event = make_event(
        content="mày ở phòng nào vậy?",
        channel_type=ChannelType.DM,
    )
    disclosure = DisclosureGate().evaluate(
        content=event.content,
        relationship_tier=RelationshipTier.STRANGER,
    )

    view = PersonaViewSelector().select(
        event=event,
        specification=specification,
        relationship_tier=RelationshipTier.STRANGER,
        disclosure=disclosure,
    )

    selected_ids = {rule.rule_id for rule in view.all_rules()}
    all_ids = {rule.rule_id for rule in specification.all_rules()}
    assert selected_ids < all_ids
    assert {
        "bio.location",
        "boundary.privacy_intrusion",
        "disclosure.stranger_sensitive",
        "style.vietnamese",
        "presentation.dialogue_only",
    } <= selected_ids
    assert all(rule.source_refs for rule in view.all_rules())


def test_style_selection_cannot_change_participation_policy() -> None:
    specification = _specification()
    vietnamese = make_event(
        event_id="vi",
        content="mày xem cái này được không?",
        channel_type=ChannelType.DM,
    )
    english = make_event(
        event_id="en",
        content="can you look at this?",
        channel_type=ChannelType.DM,
    )
    observation = ObservationSnapshot(
        conversation_id="conversation-001",
        agent_actor_id="agent-001",
        state_version=0,
    )

    decisions = []
    views = []
    disclosures = []
    for event in (vietnamese, english):
        disclosure = DisclosureGate().evaluate(
            content=event.content,
            relationship_tier=RelationshipTier.STRANGER,
        )
        view = PersonaViewSelector().select(
            event=event,
            specification=specification,
            relationship_tier=RelationshipTier.STRANGER,
            disclosure=disclosure,
        )
        influence = PersonaParticipationPolicy().evaluate(view)
        attention = AttentionPolicy().evaluate(event, observation)
        decisions.append(
            ParticipationPolicy().decide(
                cycle_id=f"cycle-{event.event_id}",
                event=event,
                attention=attention,
                agent_actor_id="agent-001",
                persona_preference_score=influence.score,
                persona_reason_codes=influence.reason_codes,
            )
        )
        views.append(view)
        disclosures.append(disclosure)

    assert decisions[0].outcome == decisions[1].outcome
    assert decisions[0].score_breakdown.persona_preference == -0.05
    assert decisions[1].score_breakdown.persona_preference == -0.05
    assert {rule.rule_id for rule in views[0].style_rules} != {
        rule.rule_id for rule in views[1].style_rules
    }
    plans = [
        MockLanguagePort().create_content_plan(
            event,
            decision,
            persona_view=view,
            disclosure=disclosure,
        )
        for event, decision, view, disclosure in zip(
            (vietnamese, english),
            decisions,
            views,
            disclosures,
            strict=True,
        )
    ]
    vietnamese_style = {
        constraint for constraint in plans[0].constraints if constraint.startswith("style_rule:")
    }
    english_style = {
        constraint for constraint in plans[1].constraints if constraint.startswith("style_rule:")
    }
    assert vietnamese_style != english_style
