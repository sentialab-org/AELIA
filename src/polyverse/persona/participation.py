from __future__ import annotations

from polyverse.persona.models import (
    PersonaParticipationInfluence,
    PersonaView,
    RelationshipTier,
)

PERSONA_PARTICIPATION_POLICY_VERSION = "persona-participation-v1"


class PersonaParticipationPolicy:
    def evaluate(self, view: PersonaView) -> PersonaParticipationInfluence:
        policy_rule_ids = {rule.rule_id for rule in view.policy_rules}
        score = 0.0
        reason_codes: list[str] = []
        applied_rule_ids: list[str] = []

        if (
            view.relationship_tier is RelationshipTier.STRANGER
            and "participation.observe_first" in policy_rule_ids
        ):
            score -= 0.05
            reason_codes.append("persona_prefers_observation_with_stranger")
            applied_rule_ids.append("participation.observe_first")
        elif (
            view.relationship_tier is RelationshipTier.TRUSTED
            and "participation.help_contextual" in policy_rule_ids
        ):
            score += 0.10
            reason_codes.append("persona_allows_more_engagement_with_trusted_person")
            applied_rule_ids.append("participation.help_contextual")

        if "boundary.role_pressure" in policy_rule_ids:
            score -= 0.10
            reason_codes.append("persona_resists_generic_assistant_pressure")
            applied_rule_ids.append("boundary.role_pressure")

        return PersonaParticipationInfluence(
            policy_version=PERSONA_PARTICIPATION_POLICY_VERSION,
            score=round(score, 6),
            reason_codes=tuple(reason_codes),
            rule_ids=tuple(applied_rule_ids),
        )
