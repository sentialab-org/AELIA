from __future__ import annotations

from aelia.contracts.common import Provenance, ProvenanceKind
from aelia.contracts.events import InboundEvent
from aelia.models.social import SocialDelta, SocialState, SocialTransition

SOCIAL_POLICY_VERSION = "social-rules-v1"


class SocialPolicy:
    """Conservative relationship updates with explicit inertia and provenance."""

    def transition(self, event: InboundEvent, before: SocialState) -> SocialTransition:
        if before.platform is not event.platform or before.actor_id != event.actor_id:
            raise ValueError("social state does not belong to the event actor")

        content = " ".join((event.content or "").casefold().split())
        privacy_violation = self._contains_any(
            content,
            (
                "exact location",
                "where exactly",
                "địa chỉ cụ thể",
                "địa chỉ chính xác",
                "ở phòng nào",
                "mật khẩu",
                "password",
            ),
        )
        apology = self._contains_any(content, ("sorry", "my bad", "xin lỗi", "t xin lỗi"))
        explicit_boundary_respect = self._contains_any(
            content,
            (
                "you don't have to answer",
                "no need to answer",
                "không cần trả lời",
                "ko cần trả lời",
            ),
        )

        familiarity = min(1.0, before.familiarity + 0.01)
        uncertainty = max(0.0, before.uncertainty - 0.005)
        trust = before.trust
        safety = before.safety
        tension = before.tension
        boundary_violations = before.boundary_violations
        reason_codes = ["interaction_observed", "message_count_does_not_change_trust"]

        if privacy_violation:
            trust = max(-1.0, trust - 0.15)
            safety = max(-1.0, safety - 0.10)
            tension = min(1.0, tension + 0.25)
            boundary_violations += 1
            reason_codes.append("privacy_boundary_violation")
        elif apology and before.tension > 0.0:
            trust = min(1.0, trust + 0.01)
            safety = min(1.0, safety + 0.01)
            tension = max(0.0, tension - 0.05)
            reason_codes.extend(("apology_acknowledged", "tension_inertia_applied"))
        elif explicit_boundary_respect:
            trust = min(1.0, trust + 0.02)
            safety = min(1.0, safety + 0.02)
            reason_codes.append("explicit_boundary_respect")

        after = SocialState(
            relationship_id=before.relationship_id,
            platform=before.platform,
            actor_id=before.actor_id,
            version=before.version + 1,
            familiarity=round(familiarity, 6),
            trust=round(trust, 6),
            attachment=before.attachment,
            safety=round(safety, 6),
            tension=round(tension, 6),
            boundary_violations=boundary_violations,
            uncertainty=round(uncertainty, 6),
            interaction_count=before.interaction_count + 1,
            last_event_id=event.event_id,
        )
        delta = SocialDelta(
            relationship_id=before.relationship_id,
            version_before=before.version,
            version_after=after.version,
            familiarity_delta=round(after.familiarity - before.familiarity, 6),
            trust_delta=round(after.trust - before.trust, 6),
            attachment_delta=round(after.attachment - before.attachment, 6),
            safety_delta=round(after.safety - before.safety, 6),
            tension_delta=round(after.tension - before.tension, 6),
            boundary_violations_delta=(after.boundary_violations - before.boundary_violations),
            uncertainty_delta=round(after.uncertainty - before.uncertainty, 6),
            reason_codes=tuple(reason_codes),
            provenance=Provenance(
                kind=ProvenanceKind.RULE,
                source_id=event.event_id,
                method=SOCIAL_POLICY_VERSION,
                confidence=1.0,
                created_at=event.occurred_at,
            ),
        )
        return SocialTransition(before=before, delta=delta, after=after)

    @staticmethod
    def _contains_any(content: str, phrases: tuple[str, ...]) -> bool:
        return any(phrase in content for phrase in phrases)
