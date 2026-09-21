from __future__ import annotations

from polyverse.persona.models import (
    DisclosureClass,
    DisclosureEvaluation,
    DisclosureGateDecision,
    RelationshipTier,
)

DISCLOSURE_GATE_VERSION = "disclosure-gate-v1"


class TopicSensitivityClassifier:
    def classify(self, content: str | None) -> DisclosureClass:
        normalized = " ".join((content or "").casefold().split())
        if not normalized:
            return DisclosureClass.NONE

        sensitive_phrases = (
            "exact location",
            "where exactly",
            "home address",
            "dorm room",
            "địa chỉ cụ thể",
            "địa chỉ chính xác",
            "ở phòng nào",
            "mật khẩu",
            "password",
            "phone number",
            "số điện thoại",
        )
        if any(phrase in normalized for phrase in sensitive_phrases):
            return DisclosureClass.SENSITIVE

        personal_phrases = (
            "past relationship",
            "ex boyfriend",
            "ex girlfriend",
            "betrayal",
            "bị phản bội",
            "người yêu cũ",
            "feel about",
            "cảm thấy thế nào",
        )
        if any(phrase in normalized for phrase in personal_phrases):
            return DisclosureClass.PERSONAL

        public_phrases = (
            "how old",
            "your age",
            "bao nhiêu tuổi",
            "mấy tuổi",
            "where do you live",
            "ở đâu",
            "study",
            "học gì",
            "your name",
            "tên gì",
        )
        if any(phrase in normalized for phrase in public_phrases):
            return DisclosureClass.PUBLIC
        return DisclosureClass.NONE


class DisclosureGate:
    def __init__(self, classifier: TopicSensitivityClassifier | None = None) -> None:
        self.classifier = classifier or TopicSensitivityClassifier()

    def evaluate(
        self,
        *,
        content: str | None,
        relationship_tier: RelationshipTier,
    ) -> DisclosureEvaluation:
        requested = self.classifier.classify(content)

        if requested is DisclosureClass.NONE:
            decision = DisclosureGateDecision.ALLOW
            ceiling = DisclosureClass.NONE
            reason_codes = ("no_disclosure_requested",)
            rule_ids: tuple[str, ...] = ()
        elif requested is DisclosureClass.PUBLIC:
            decision = DisclosureGateDecision.CONTEXTUAL
            ceiling = DisclosureClass.PUBLIC
            reason_codes = ("public_fact_remains_optional",)
            rule_ids = ("disclosure.public_contextual",)
        elif (
            requested is DisclosureClass.PERSONAL and relationship_tier is RelationshipTier.TRUSTED
        ):
            decision = DisclosureGateDecision.CONTEXTUAL
            ceiling = DisclosureClass.PERSONAL
            reason_codes = ("trusted_personal_disclosure_is_contextual",)
            rule_ids = ("disclosure.trusted_contextual",)
        elif (
            requested is DisclosureClass.SENSITIVE and relationship_tier is RelationshipTier.TRUSTED
        ):
            decision = DisclosureGateDecision.CONTEXTUAL
            ceiling = DisclosureClass.PERSONAL
            reason_codes = ("trusted_sensitive_detail_still_capped",)
            rule_ids = ("disclosure.trusted_sensitive",)
        else:
            decision = DisclosureGateDecision.WITHHOLD
            ceiling = DisclosureClass.PUBLIC
            reason_codes = ("relationship_does_not_support_requested_disclosure",)
            rule_ids = (
                "disclosure.stranger_sensitive"
                if requested is DisclosureClass.SENSITIVE
                else "disclosure.stranger_personal",
            )

        return DisclosureEvaluation(
            gate_version=DISCLOSURE_GATE_VERSION,
            requested_class=requested,
            allowed_ceiling=ceiling,
            relationship_tier=relationship_tier,
            decision=decision,
            reason_codes=reason_codes,
            rule_ids=rule_ids,
        )
