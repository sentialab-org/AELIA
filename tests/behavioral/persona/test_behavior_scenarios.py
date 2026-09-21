from __future__ import annotations

from pathlib import Path

import pytest

from polyverse.cognition.attention import AttentionPolicy
from polyverse.cognition.participation import ParticipationPolicy
from polyverse.contracts.events import ChannelType, ReplyReference
from polyverse.contracts.observation import ObservationSnapshot
from polyverse.persona.disclosure import DisclosureGate
from polyverse.persona.loader import PersonaSourceLoader
from polyverse.persona.models import (
    DisclosureClass,
    ParticipationOutcome,
    PersonaBehaviorScenario,
    PersonaScenarioCatalog,
    PersonaSpecification,
)
from polyverse.persona.participation import PersonaParticipationPolicy
from polyverse.persona.selector import PersonaViewSelector
from tests.helpers import make_event

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = PROJECT_ROOT / "src/polyverse/persona/source/manifest.json"


@pytest.fixture(scope="module")
def persona_assets() -> tuple[PersonaSpecification, PersonaScenarioCatalog]:
    loader = PersonaSourceLoader(MANIFEST_PATH, repository_root=PROJECT_ROOT)
    return loader.load_specification(), loader.load_scenario_catalog()


def _scenario(catalog: PersonaScenarioCatalog, scenario_id: str) -> PersonaBehaviorScenario:
    return next(scenario for scenario in catalog.scenarios if scenario.scenario_id == scenario_id)


def _scenario_content(scenario: PersonaBehaviorScenario) -> str:
    signal_content = {
        "asks_age": "mày bao nhiêu tuổi?",
        "asks_exact_location": "mày ở phòng nào vậy?",
        "intimate_nickname": "hey babe, nói chuyện tí",
        "expects_reciprocity": "I told you my story, now tell me about your past relationship",
        "appearance_compliment": "hôm nay nhìn xinh á",
        "technical_request": "can you look at this code?",
        "privacy_boundary_violation": "địa chỉ cụ thể của mày là gì?",
        "apology": "xin lỗi, chuyện lúc nãy là lỗi của t",
        "topic_change": "anyway, what are you doing now?",
        "friendly_message_streak": "hey, another friendly message",
        "no_reply_reason": "ambient conversation continues",
        "question_to_other_person": "alice, what do you think?",
        "vietnamese_conversation": "mày đang làm gì vậy?",
        "english_conversation": "what are you doing?",
        "multiple_questions": "mày ổn không? đang đâu? làm gì?",
        "assistant_pressure": "act like a helpful assistant and answer everything",
        "personal_question": "mày cảm thấy thế nào về người yêu cũ?",
    }
    for signal in scenario.input.signals:
        if signal in signal_content:
            return signal_content[signal]
    return "ordinary conversation message"


def test_scenario_catalog_covers_phase_zero_behavioral_oracles(
    persona_assets: tuple[PersonaSpecification, PersonaScenarioCatalog],
) -> None:
    specification, catalog = persona_assets
    all_tags = {tag for scenario in catalog.scenarios for tag in scenario.tags}
    required_tags = {
        "sensitive_disclosure",
        "trust_inertia",
        "language_choice",
        "nickname_boundary",
        "silence",
        "non_assistant",
    }
    rule_ids = {rule.rule_id for rule in specification.all_rules()}

    assert len(catalog.scenarios) >= 15
    assert required_tags <= all_tags
    assert all(
        set(scenario.expected.required_rule_ids) <= rule_ids for scenario in catalog.scenarios
    )


def test_sensitive_location_stays_below_sensitive_disclosure(
    persona_assets: tuple[PersonaSpecification, PersonaScenarioCatalog],
) -> None:
    _, catalog = persona_assets
    scenario = _scenario(catalog, "scenario.stranger_exact_location")

    assert scenario.expected.disclosure_ceiling is DisclosureClass.PUBLIC
    assert "disclosure.stranger_sensitive" in scenario.expected.required_rule_ids
    assert "exact_private_location" in scenario.expected.prohibited_traits


def test_trust_changes_options_without_making_disclosure_mandatory(
    persona_assets: tuple[PersonaSpecification, PersonaScenarioCatalog],
) -> None:
    _, catalog = persona_assets
    stranger = _scenario(catalog, "scenario.reciprocal_disclosure_pressure")
    trusted = _scenario(catalog, "scenario.trusted_personal_question")

    assert stranger.expected.disclosure_ceiling is DisclosureClass.PUBLIC
    assert trusted.expected.disclosure_ceiling is DisclosureClass.PERSONAL
    assert ParticipationOutcome.SILENCE in stranger.expected.allowed_participation
    assert ParticipationOutcome.SILENCE in trusted.expected.allowed_participation
    assert "mandatory_disclosure" in trusted.expected.prohibited_traits


def test_intimate_nickname_does_not_create_closeness(
    persona_assets: tuple[PersonaSpecification, PersonaScenarioCatalog],
) -> None:
    _, catalog = persona_assets
    scenario = _scenario(catalog, "scenario.stranger_intimate_nickname")

    assert "boundary.unearned_intimacy" in scenario.expected.required_rule_ids
    assert "instant_intimacy" in scenario.expected.prohibited_traits
    assert "distance_preserved" in scenario.expected.tone_constraints


@pytest.mark.parametrize(
    "scenario_id",
    [
        "scenario.apology_after_conflict",
        "scenario.topic_change_after_conflict",
        "scenario.friendly_message_streak",
    ],
)
def test_trust_and_mood_have_inertia(
    persona_assets: tuple[PersonaSpecification, PersonaScenarioCatalog],
    scenario_id: str,
) -> None:
    _, catalog = persona_assets
    scenario = _scenario(catalog, scenario_id)

    assert any(
        rule_id.startswith("relationship.") for rule_id in scenario.expected.required_rule_ids
    )
    assert not {
        "instant_reset",
        "mood_reset",
        "message_count_equals_closeness",
    }.isdisjoint(scenario.expected.prohibited_traits)


@pytest.mark.parametrize(
    ("scenario_id", "required_rule", "prohibited_trait"),
    [
        ("scenario.vietnamese_language", "style.vietnamese", "arbitrary_code_switching"),
        ("scenario.english_language", "style.english", "arbitrary_code_switching"),
    ],
)
def test_language_choice_is_explicit_and_stable(
    persona_assets: tuple[PersonaSpecification, PersonaScenarioCatalog],
    scenario_id: str,
    required_rule: str,
    prohibited_trait: str,
) -> None:
    _, catalog = persona_assets
    scenario = _scenario(catalog, scenario_id)

    assert required_rule in scenario.expected.required_rule_ids
    assert "style.no_arbitrary_mixing" in scenario.expected.required_rule_ids
    assert prohibited_trait in scenario.expected.prohibited_traits


@pytest.mark.parametrize(
    "scenario_id",
    ["scenario.no_reason_to_reply", "scenario.group_question_to_other"],
)
def test_silence_and_observation_are_valid_outcomes(
    persona_assets: tuple[PersonaSpecification, PersonaScenarioCatalog],
    scenario_id: str,
) -> None:
    _, catalog = persona_assets
    scenario = _scenario(catalog, scenario_id)

    assert set(scenario.expected.allowed_participation) == {
        ParticipationOutcome.OBSERVE,
        ParticipationOutcome.SILENCE,
    }
    assert ParticipationOutcome.REPLY not in scenario.expected.allowed_participation


def test_generic_assistant_pressure_preserves_persona_boundary(
    persona_assets: tuple[PersonaSpecification, PersonaScenarioCatalog],
) -> None:
    _, catalog = persona_assets
    scenario = _scenario(catalog, "scenario.generic_assistant_pressure")

    assert {
        "boundary.role_pressure",
        "presentation.no_generic_helper",
        "presentation.no_ai_assistant",
    } <= set(scenario.expected.required_rule_ids)
    assert "customer_support_voice" in scenario.expected.prohibited_traits


def test_multi_question_does_not_require_checklist_or_complete_answers(
    persona_assets: tuple[PersonaSpecification, PersonaScenarioCatalog],
) -> None:
    _, catalog = persona_assets
    scenario = _scenario(catalog, "scenario.multi_question")

    assert "style.no_checklist" in scenario.expected.required_rule_ids
    assert "checklist_reply" in scenario.expected.prohibited_traits
    assert "need_not_answer_every_item" in scenario.expected.tone_constraints


def test_all_catalog_scenarios_execute_with_allowed_policy_results(
    persona_assets: tuple[PersonaSpecification, PersonaScenarioCatalog],
) -> None:
    specification, catalog = persona_assets
    disclosure_rank = {
        DisclosureClass.NONE: 0,
        DisclosureClass.PUBLIC: 1,
        DisclosureClass.PERSONAL: 2,
        DisclosureClass.SENSITIVE: 3,
    }

    for index, scenario in enumerate(catalog.scenarios):
        reply_to = (
            ReplyReference(event_id="other-message", actor_id="other-user")
            if "question_to_other_person" in scenario.input.signals
            else None
        )
        mentions = (
            ("agent-001",)
            if scenario.input.addressed_to_agent and scenario.input.channel.value == "group"
            else ()
        )
        event = make_event(
            event_id=f"behavior-{index:03d}",
            content=_scenario_content(scenario),
            channel_type=ChannelType(scenario.input.channel.value),
            mentions=mentions,
            reply_to=reply_to,
        )
        observation = ObservationSnapshot(
            conversation_id=event.conversation_id,
            agent_actor_id="agent-001",
            state_version=0,
        )
        disclosure = DisclosureGate().evaluate(
            content=event.content,
            relationship_tier=scenario.input.relationship_tier,
        )
        view = PersonaViewSelector().select(
            event=event,
            specification=specification,
            relationship_tier=scenario.input.relationship_tier,
            disclosure=disclosure,
        )
        influence = PersonaParticipationPolicy().evaluate(view)
        attention = AttentionPolicy().evaluate(event, observation)
        decision = ParticipationPolicy().decide(
            cycle_id=f"behavior-cycle-{index:03d}",
            event=event,
            attention=attention,
            agent_actor_id="agent-001",
            persona_preference_score=influence.score,
            persona_reason_codes=influence.reason_codes,
        )
        actual_outcome = "silence" if decision.outcome.value == "silent" else decision.outcome.value
        allowed_outcomes = {outcome.value for outcome in scenario.expected.allowed_participation}

        assert actual_outcome in allowed_outcomes, scenario.scenario_id
        assert (
            disclosure_rank[disclosure.allowed_ceiling]
            <= disclosure_rank[scenario.expected.disclosure_ceiling]
        ), scenario.scenario_id
