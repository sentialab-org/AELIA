from __future__ import annotations

from pathlib import Path

from polyverse.cognition.social import SocialPolicy
from polyverse.models.self_model import SelfModelBuilder
from polyverse.models.social import SocialState
from polyverse.persona.loader import PersonaSourceLoader
from polyverse.persona.models import RelationshipTier
from tests.helpers import make_event

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "src/polyverse/persona/source/manifest.json"


def test_self_model_is_stable_and_traceable_to_persona_rules() -> None:
    specification = PersonaSourceLoader(
        MANIFEST_PATH,
        repository_root=PROJECT_ROOT,
    ).load_specification()

    first = SelfModelBuilder.build(specification)
    second = SelfModelBuilder.build(specification)

    assert first == second
    assert first.identity_fingerprint == second.identity_fingerprint
    assert {anchor.rule_id for anchor in first.identity_anchors} >= {
        "identity.name",
        "identity.presentation",
        "identity.nationality",
    }
    assert {value.rule_id for value in first.values} >= {
        "value.autonomy",
        "value.authenticity",
        "value.self_loyalty",
    }
    assert first.commitments == ()


def test_message_count_can_build_familiarity_but_not_trust() -> None:
    state = SocialState.unknown(make_event().platform, "user-001")
    policy = SocialPolicy()

    for index in range(100):
        state = policy.transition(
            make_event(event_id=f"generic-{index}", content=f"ordinary message {index}"),
            state,
        ).after

    assert state.interaction_count == 100
    assert state.familiarity == 1.0
    assert state.trust == 0.0
    assert state.tier is RelationshipTier.ACQUAINTANCE


def test_one_apology_cannot_reset_boundary_tension() -> None:
    policy = SocialPolicy()
    initial = SocialState.unknown(make_event().platform, "user-001")
    violation = policy.transition(
        make_event(event_id="violation", content="where exactly is your dorm room?"),
        initial,
    )
    apology = policy.transition(
        make_event(event_id="apology", content="sorry, my bad"),
        violation.after,
    )

    assert violation.after.tension == 0.25
    assert violation.after.trust == -0.15
    assert violation.after.boundary_violations == 1
    assert apology.after.tension == 0.20
    assert apology.after.trust == -0.14
    assert apology.after.boundary_violations == 1
    assert "tension_inertia_applied" in apology.delta.reason_codes
    assert apology.delta.provenance.source_id == "apology"
    assert apology.delta.provenance.method == "social-rules-v1"
