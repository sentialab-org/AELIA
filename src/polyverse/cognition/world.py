from __future__ import annotations

import hashlib

from polyverse.contracts.common import Provenance, ProvenanceKind
from polyverse.contracts.events import InboundEvent
from polyverse.models.belief import BeliefTransition
from polyverse.models.perception import PerceptionResult
from polyverse.models.world import WorldModel, WorldStatement, WorldStatementKind

WORLD_MODEL_POLICY_VERSION = "world-projection-v1"


class WorldModelPolicy:
    def project(
        self,
        *,
        event: InboundEvent,
        perception: PerceptionResult,
        beliefs: BeliefTransition,
    ) -> WorldModel:
        statements = [
            self._statement(
                kind=WorldStatementKind.OBSERVATION,
                subject=event.conversation_id,
                predicate="channel_type",
                value=event.channel_type.value,
                confidence=1.0,
                source_ids=(event.event_id,),
            ),
            self._capability(
                event,
                "send_message",
                event.permissions.can_send_message,
            ),
            self._capability(event, "reply", event.permissions.can_reply),
            self._capability(event, "react", event.permissions.can_react),
        ]
        statements.extend(
            self._statement(
                kind=WorldStatementKind.HYPOTHESIS,
                subject=claim.subject,
                predicate=claim.predicate,
                value=claim.value,
                confidence=claim.confidence,
                source_ids=(claim.claim_id, event.event_id),
            )
            for claim in perception.claim_candidates
        )

        belief_by_id = {
            belief.belief_id: belief for belief in (*beliefs.before.records, *beliefs.upserts)
        }
        statements.extend(
            self._statement(
                kind=WorldStatementKind.BELIEF_REFERENCE,
                subject=belief.subject,
                predicate=belief.predicate,
                value=belief.value,
                confidence=belief.confidence,
                source_ids=(belief.belief_id,),
            )
            for belief in sorted(belief_by_id.values(), key=lambda item: item.belief_id)
        )
        outbound_possible = event.permissions.can_send_message and event.permissions.can_reply
        statements.append(
            self._statement(
                kind=WorldStatementKind.PREDICTION,
                subject=event.conversation_id,
                predicate="communicative_action_possible",
                value="yes" if outbound_possible else "no",
                confidence=1.0,
                source_ids=(event.event_id,),
            )
        )
        return WorldModel(
            model_version=WORLD_MODEL_POLICY_VERSION,
            scope_id=f"{event.platform.value}:{event.conversation_id}",
            platform=event.platform,
            current_event_id=event.event_id,
            entity_ids=(event.actor_id, event.conversation_id),
            statements=tuple(statements),
            rebuildable=True,
            provenance=Provenance(
                kind=ProvenanceKind.RULE,
                source_id=event.event_id,
                method=WORLD_MODEL_POLICY_VERSION,
                confidence=1.0,
                created_at=event.occurred_at,
            ),
        )

    def _capability(
        self,
        event: InboundEvent,
        capability: str,
        available: bool,
    ) -> WorldStatement:
        return self._statement(
            kind=WorldStatementKind.CAPABILITY,
            subject=event.platform.value,
            predicate=capability,
            value="available" if available else "unavailable",
            confidence=1.0,
            source_ids=(event.event_id,),
        )

    @staticmethod
    def _statement(
        *,
        kind: WorldStatementKind,
        subject: str,
        predicate: str,
        value: str,
        confidence: float,
        source_ids: tuple[str, ...],
    ) -> WorldStatement:
        material = "\x1f".join((kind.value, subject, predicate, value, *source_ids))
        digest = hashlib.sha256(material.encode()).hexdigest()[:24]
        return WorldStatement(
            statement_id=f"world:{digest}",
            kind=kind,
            subject=subject,
            predicate=predicate,
            value=value,
            confidence=confidence,
            source_ids=source_ids,
        )
