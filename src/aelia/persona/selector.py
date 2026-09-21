from __future__ import annotations

from collections.abc import Mapping

from aelia.contracts.events import InboundEvent
from aelia.persona.models import (
    ConversationLanguage,
    DisclosureEvaluation,
    PersonaRule,
    PersonaSpecification,
    PersonaView,
    RelationshipTier,
    SelectedPersonaRule,
)

PERSONA_SELECTOR_VERSION = "persona-selector-v1"


class PersonaViewSelector:
    def select(
        self,
        *,
        event: InboundEvent,
        specification: PersonaSpecification,
        relationship_tier: RelationshipTier,
        disclosure: DisclosureEvaluation,
    ) -> PersonaView:
        language = self.detect_language(event.content)
        normalized = " ".join((event.content or "").casefold().split())

        identity_ids = ["identity.name"]
        if any(phrase in normalized for phrase in ("age", "tuổi")):
            identity_ids.append("bio.age")
        if any(
            phrase in normalized
            for phrase in ("where", "ở đâu", "location", "phòng nào", "địa chỉ")
        ):
            identity_ids.append("bio.location")
        if any(
            phrase in normalized for phrase in ("betrayal", "phản bội", "relationship", "người yêu")
        ):
            identity_ids.append("bio.betrayal")

        policy_ids = [
            "value.autonomy",
            "value.authenticity",
            "participation.help_contextual",
            "participation.answer_not_automatic",
            "participation.silence_allowed",
        ]
        if relationship_tier is RelationshipTier.STRANGER:
            policy_ids.extend(
                (
                    "relationship.closeness_earned",
                    "relationship.observe_first",
                    "participation.observe_first",
                )
            )
        if disclosure.decision.value == "withhold":
            policy_ids.append("boundary.privacy_intrusion")
        if any(phrase in normalized for phrase in ("baby", "babe", "bé yêu", "cưng")):
            policy_ids.append("boundary.unearned_intimacy")
        if any(word in normalized for word in ("assistant", "helpful", "hữu ích")):
            policy_ids.append("boundary.role_pressure")

        style_ids = [
            "style.casual_flow",
            "style.brevity",
            "style.affect_implicit",
            "style.no_overediting",
            "style.no_arbitrary_mixing",
        ]
        if (event.content or "").count("?") > 1:
            style_ids.append("style.no_checklist")
        if language is ConversationLanguage.VI:
            style_ids.extend(("style.vietnamese", "style.slang_organic"))
        elif language is ConversationLanguage.EN:
            style_ids.append("style.english")

        presentation_ids = [
            "presentation.name",
            "presentation.no_ai_assistant",
            "presentation.no_meta_explanation",
            "presentation.dialogue_only",
            "presentation.no_generic_helper",
            "presentation.no_manufactured_edge",
        ]

        rule_by_id = {rule.rule_id: rule for rule in specification.all_rules()}
        return PersonaView(
            selector_version=PERSONA_SELECTOR_VERSION,
            persona_id=specification.persona_id,
            specification_version=specification.specification_version,
            language=language,
            relationship_tier=relationship_tier,
            identity_rules=self._materialize(identity_ids, "identity", rule_by_id),
            policy_rules=self._materialize(policy_ids, "policy", rule_by_id),
            disclosure_rules=self._materialize(
                list(disclosure.rule_ids),
                "disclosure",
                rule_by_id,
            ),
            style_rules=self._materialize(style_ids, "style", rule_by_id),
            presentation_rules=self._materialize(
                presentation_ids,
                "presentation",
                rule_by_id,
            ),
        )

    @staticmethod
    def detect_language(content: str | None) -> ConversationLanguage:
        normalized = f" {(content or '').casefold()} "
        vietnamese_markers = (
            "ă",
            "â",
            "đ",
            "ê",
            "ô",
            "ơ",
            "ư",
            "à",
            "á",
            "ả",
            "ã",
            "ạ",
            " không ",
            " mình ",
            " mày ",
            " tuổi ",
        )
        has_vietnamese = any(marker in normalized for marker in vietnamese_markers)
        return ConversationLanguage.VI if has_vietnamese else ConversationLanguage.EN

    @staticmethod
    def _materialize(
        rule_ids: list[str],
        category: str,
        rule_by_id: Mapping[str, PersonaRule],
    ) -> tuple[SelectedPersonaRule, ...]:
        selected: list[SelectedPersonaRule] = []
        for rule_id in dict.fromkeys(rule_ids):
            try:
                rule = rule_by_id[rule_id]
            except KeyError as exc:
                raise ValueError(f"persona selector references unknown rule: {rule_id}") from exc
            selected.append(
                SelectedPersonaRule(
                    rule_id=rule.rule_id,
                    category=category,
                    instruction=rule.instruction,
                    source_refs=rule.source_refs,
                )
            )
        return tuple(selected)
