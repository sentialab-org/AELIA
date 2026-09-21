from __future__ import annotations

from polyverse.contracts.common import Provenance, ProvenanceKind
from polyverse.contracts.events import ChannelType, InboundEvent
from polyverse.contracts.observation import ObservationSnapshot
from polyverse.models.cognition import AppraisalResult
from polyverse.models.perception import PerceptionResult
from polyverse.models.social import SocialState
from polyverse.models.world import WorldModel
from polyverse.persona.models import DisclosureEvaluation, PersonaView

APPRAISAL_POLICY_VERSION = "appraisal-rules-v1"


class AppraisalPolicy:
    def appraise(
        self,
        *,
        event: InboundEvent,
        observation: ObservationSnapshot,
        perception: PerceptionResult,
        social: SocialState,
        persona_view: PersonaView,
        disclosure: DisclosureEvaluation,
        world: WorldModel | None = None,
    ) -> AppraisalResult:
        policy_rule_ids = {rule.rule_id for rule in persona_view.policy_rules}
        boundary_pressure = disclosure.decision.value == "withhold"
        role_pressure = "boundary.role_pressure" in policy_rule_ids
        addressed = (
            event.channel_type is ChannelType.DM
            or observation.agent_actor_id in event.mentions
            or (
                event.reply_to is not None and event.reply_to.actor_id == observation.agent_actor_id
            )
        )
        normalized = " ".join((event.content or "").casefold().split())
        repeated = any(
            " ".join((message.content or "").casefold().split()) == normalized
            for message in observation.recent_messages
            if normalized
        )

        value_alignment = -0.8 if boundary_pressure else (-0.6 if role_pressure else 0.0)
        novelty = 0.15 if repeated else 0.7
        communicative_action_available = (
            world.capability_available("send_message") and world.capability_available("reply")
            if world is not None
            else event.permissions.can_send_message and event.permissions.can_reply
        )
        controllability = 0.8 if communicative_action_available else 0.2
        social_relevance = 0.9 if addressed else 0.2
        responsibility = 0.8 if boundary_pressure or role_pressure else 0.2
        reason_codes = ["goal_relevance_placeholder", "rule_first_appraisal"]
        if world is not None:
            reason_codes.append("world_capabilities_informed_controllability")
        if boundary_pressure:
            reason_codes.append("privacy_or_disclosure_boundary_relevant")
        if role_pressure:
            reason_codes.append("autonomy_value_relevant")
        if social.tension > 0.0:
            reason_codes.append("relationship_tension_carried_forward")

        return AppraisalResult(
            policy_version=APPRAISAL_POLICY_VERSION,
            goal_relevance=0.0,
            goal_congruence=-0.6 if boundary_pressure else 0.0,
            value_alignment=value_alignment,
            novelty=novelty,
            certainty=round(1.0 - perception.uncertainty, 6),
            controllability=controllability,
            social_relevance=social_relevance,
            agency=0.8,
            responsibility=responsibility,
            expectedness=round(1.0 - novelty, 6),
            reason_codes=tuple(reason_codes),
            provenance=Provenance(
                kind=ProvenanceKind.RULE,
                source_id=event.event_id,
                method=APPRAISAL_POLICY_VERSION,
                confidence=1.0,
                created_at=event.occurred_at,
            ),
        )
