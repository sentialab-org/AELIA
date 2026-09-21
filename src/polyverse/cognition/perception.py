from __future__ import annotations

import hashlib
import re

from polyverse.contracts.common import Provenance, ProvenanceKind
from polyverse.contracts.events import InboundEvent
from polyverse.contracts.participation import AttentionResult, ProcessingMode
from polyverse.models.perception import (
    ClaimCandidate,
    EpistemicKind,
    ObservedSignal,
    PerceptionDepth,
    PerceptionResult,
)

PERCEPTION_POLICY_VERSION = "perception-rules-v1"


class PerceptionPolicy:
    def perceive(
        self,
        *,
        event: InboundEvent,
        attention: AttentionResult,
    ) -> PerceptionResult:
        provenance = Provenance(
            kind=ProvenanceKind.RULE,
            source_id=event.event_id,
            method=PERCEPTION_POLICY_VERSION,
            confidence=1.0,
            created_at=event.occurred_at,
        )
        observation_id = f"{event.event_id}:message_observed"
        observed = ObservedSignal(
            observation_id=observation_id,
            kind=EpistemicKind.OBSERVATION,
            statement=f"Actor {event.actor_id} produced inbound event {event.event_id}.",
            confidence=1.0,
            uncertainty=0.0,
            provenance=provenance,
        )
        if attention.processing_mode is ProcessingMode.LIGHTWEIGHT:
            return PerceptionResult(
                policy_version=PERCEPTION_POLICY_VERSION,
                depth=PerceptionDepth.LIGHTWEIGHT,
                observed_signals=(observed,),
                claim_candidates=(),
                uncertainty=0.8,
                reason_codes=("lightweight_observation_only", "claims_not_promoted_to_facts"),
            )

        candidates = self._extract_self_report_candidates(
            event=event,
            observation_id=observation_id,
            provenance=provenance,
        )
        uncertainty = 0.45 if candidates else 0.6
        return PerceptionResult(
            policy_version=PERCEPTION_POLICY_VERSION,
            depth=PerceptionDepth.DEEP,
            observed_signals=(observed,),
            claim_candidates=candidates,
            uncertainty=uncertainty,
            reason_codes=(
                "deep_rule_first_perception",
                "self_reports_are_hypotheses",
                "claims_not_promoted_to_facts",
            ),
        )

    def _extract_self_report_candidates(
        self,
        *,
        event: InboundEvent,
        observation_id: str,
        provenance: Provenance,
    ) -> tuple[ClaimCandidate, ...]:
        content = " ".join((event.content or "").strip().split())
        if not content:
            return ()

        age_match = re.search(
            r"\b(?:i am|i'm|my age is|tôi|mình)\s+(\d{1,3})(?:\s+years? old|\s+tuổi)?\b",
            content.casefold(),
        )
        if age_match:
            return (
                self._candidate(
                    event=event,
                    observation_id=observation_id,
                    predicate="age",
                    value=age_match.group(1),
                    provenance=provenance,
                ),
            )

        description_match = re.search(
            r"^(?:i am|i'm|tôi là|mình là)\s+(.{1,200})$",
            content,
            flags=re.IGNORECASE,
        )
        if description_match:
            return (
                self._candidate(
                    event=event,
                    observation_id=observation_id,
                    predicate="self_description",
                    value=description_match.group(1).strip(),
                    provenance=provenance,
                ),
            )
        return ()

    @staticmethod
    def _candidate(
        *,
        event: InboundEvent,
        observation_id: str,
        predicate: str,
        value: str,
        provenance: Provenance,
    ) -> ClaimCandidate:
        material = f"{event.actor_id}\x1f{predicate}\x1f{value.casefold()}"
        claim_id = f"claim:{hashlib.sha256(material.encode()).hexdigest()[:24]}"
        return ClaimCandidate(
            claim_id=claim_id,
            subject=event.actor_id,
            predicate=predicate,
            value=value,
            kind=EpistemicKind.HYPOTHESIS,
            confidence=0.55,
            uncertainty=0.45,
            evidence_observation_ids=(observation_id,),
            provenance=provenance,
        )
