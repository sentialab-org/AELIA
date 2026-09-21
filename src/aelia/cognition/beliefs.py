from __future__ import annotations

import hashlib

from aelia.contracts.common import Provenance, ProvenanceKind
from aelia.contracts.events import InboundEvent
from aelia.models.belief import (
    BeliefEvidence,
    BeliefRecord,
    BeliefSnapshot,
    BeliefStatus,
    BeliefTransition,
)
from aelia.models.perception import PerceptionResult

BELIEF_POLICY_VERSION = "belief-rules-v1"


class BeliefPolicy:
    def transition(
        self,
        *,
        event: InboundEvent,
        perception: PerceptionResult,
        before: BeliefSnapshot,
    ) -> BeliefTransition:
        expected_scope = f"{event.platform.value}:{event.actor_id}"
        if before.scope_id != expected_scope:
            raise ValueError("belief snapshot does not belong to the event actor")

        existing_by_id = {record.belief_id: record for record in before.records}
        upserts: dict[str, BeliefRecord] = {}
        reason_codes = ["observations_are_not_automatically_facts"]

        for candidate in perception.claim_candidates:
            belief_id = self._belief_id(
                before.scope_id,
                candidate.predicate,
                candidate.value,
            )
            contradictions = tuple(
                record
                for record in before.records
                if record.subject == candidate.subject
                and record.predicate == candidate.predicate
                and record.value.casefold() != candidate.value.casefold()
            )
            evidence = BeliefEvidence(
                event_id=event.event_id,
                observation_id=candidate.evidence_observation_ids[0],
                supports=True,
                confidence=candidate.confidence,
                provenance=candidate.provenance,
            )
            existing = existing_by_id.get(belief_id)
            if existing is None:
                record = BeliefRecord(
                    belief_id=belief_id,
                    scope_id=before.scope_id,
                    subject=candidate.subject,
                    predicate=candidate.predicate,
                    value=candidate.value,
                    epistemic_kind=candidate.kind,
                    confidence=candidate.confidence,
                    status=(BeliefStatus.CONTESTED if contradictions else BeliefStatus.PROVISIONAL),
                    evidence=(evidence,),
                    contradiction_links=tuple(
                        contradiction.belief_id for contradiction in contradictions
                    ),
                    provenance=Provenance(
                        kind=ProvenanceKind.RULE,
                        source_id=event.event_id,
                        method=BELIEF_POLICY_VERSION,
                        confidence=candidate.confidence,
                        created_at=event.occurred_at,
                    ),
                    created_at=event.occurred_at,
                    updated_at=event.occurred_at,
                    decay_policy="confidence_decay_after_30d_without_support",
                )
            else:
                confidence = min(0.85, existing.confidence + 0.05)
                record = existing.model_copy(
                    update={
                        "confidence": confidence,
                        "status": (
                            BeliefStatus.ACCEPTED
                            if confidence >= 0.75 and not existing.contradiction_links
                            else existing.status
                        ),
                        "evidence": (*existing.evidence, evidence),
                        "updated_at": event.occurred_at,
                    }
                )
            upserts[record.belief_id] = record

            for contradiction in contradictions:
                links = tuple(dict.fromkeys((*contradiction.contradiction_links, record.belief_id)))
                upserts[contradiction.belief_id] = contradiction.model_copy(
                    update={
                        "status": BeliefStatus.CONTESTED,
                        "contradiction_links": links,
                        "updated_at": event.occurred_at,
                    }
                )
            reason_codes.append("hypothesis_upserted")
            if contradictions:
                reason_codes.append("contradiction_linked")

        if not perception.claim_candidates:
            reason_codes.append("no_belief_candidate")
        return BeliefTransition(
            policy_version=BELIEF_POLICY_VERSION,
            before=before,
            upserts=tuple(sorted(upserts.values(), key=lambda record: record.belief_id)),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
        )

    @staticmethod
    def _belief_id(scope_id: str, predicate: str, value: str) -> str:
        material = f"{scope_id}\x1f{predicate}\x1f{value.casefold()}"
        return f"belief:{hashlib.sha256(material.encode()).hexdigest()[:24]}"
