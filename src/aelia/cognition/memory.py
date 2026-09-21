from __future__ import annotations

import hashlib
from datetime import datetime

from aelia.cognition.action_policy import MEMORY_AWARE_ACTION_POLICY_VERSION
from aelia.contracts.actions import ExecutionResult, ExecutionStatus, OutboundAction
from aelia.contracts.common import Provenance, ProvenanceKind
from aelia.contracts.events import InboundEvent
from aelia.contracts.observation import ObservationSnapshot
from aelia.models.belief import BeliefTransition
from aelia.models.cognition import InternalState, InternalTransition
from aelia.models.goals import GoalTransition
from aelia.models.memory import (
    LearningProposal,
    LearningTarget,
    MemoryCategory,
    MemoryCategoryWeight,
    MemoryQuery,
    MemoryRecord,
    MemoryRetrievalItem,
    MemoryRetrievalResult,
    MemoryValidationStatus,
    MemoryWriteSet,
    OutcomeEvaluation,
    OutcomeStatus,
    ProposalStatus,
    ReflectionTrigger,
    ReflectionTriggerType,
)
from aelia.models.self_model import SelfModel
from aelia.models.social import SocialTransition

MEMORY_POLICY_VERSION = "memory-orchestration-v1"
RETRIEVAL_POLICY_VERSION = "memory-retrieval-v1"
OUTCOME_POLICY_VERSION = "outcome-evaluation-v1"
LEARNING_POLICY_VERSION = "learning-proposal-v1"


class MemoryPolicy:
    def build_query(
        self,
        *,
        event: InboundEvent,
        self_model: SelfModel,
        internal: InternalState,
    ) -> MemoryQuery:
        categories = tuple(MemoryCategory)
        category_weights = (
            MemoryCategoryWeight(
                category=MemoryCategory.WORKING,
                weight=1.0,
                reason_codes=("working_context_is_primary",),
            ),
            MemoryCategoryWeight(
                category=MemoryCategory.EPISODIC,
                weight=round(0.65 + internal.affect.uncertainty * 0.25, 6),
                reason_codes=("uncertainty_modulates_episode_recall",),
            ),
            MemoryCategoryWeight(
                category=MemoryCategory.SEMANTIC,
                weight=round(0.65 + internal.drives.uncertainty_reduction * 0.3, 6),
                reason_codes=("uncertainty_reduction_modulates_semantic_recall",),
            ),
            MemoryCategoryWeight(
                category=MemoryCategory.SOCIAL,
                weight=round(0.6 + internal.drives.social_connection * 0.35, 6),
                reason_codes=("social_drive_modulates_social_recall",),
            ),
            MemoryCategoryWeight(
                category=MemoryCategory.AUTOBIOGRAPHICAL,
                weight=round(0.6 + internal.drives.consistency * 0.35, 6),
                reason_codes=("consistency_drive_modulates_self_recall",),
            ),
            MemoryCategoryWeight(
                category=MemoryCategory.PROCEDURAL,
                weight=round(0.6 + internal.drives.curiosity * 0.3, 6),
                reason_codes=("curiosity_modulates_procedural_recall",),
            ),
            MemoryCategoryWeight(
                category=MemoryCategory.COMMITMENT,
                weight=round(0.65 + internal.drives.autonomy * 0.3, 6),
                reason_codes=("autonomy_modulates_commitment_recall",),
            ),
        )
        return MemoryQuery(
            query_id=f"memory-query:{event.event_id}",
            scope_ids=(
                f"conversation:{event.conversation_id}",
                f"actor:{event.platform.value}:{event.actor_id}",
                f"persona:{self_model.persona_id}",
            ),
            categories=categories,
            category_weights=category_weights,
            limit=8 + round(internal.drives.uncertainty_reduction * 4),
            reason_codes=(
                "event_context_scopes",
                "internal_state_modulates_retrieval",
                "vector_projection_not_enabled",
            ),
            provenance=Provenance(
                kind=ProvenanceKind.INTERNAL,
                source_id=internal.state_id,
                method=RETRIEVAL_POLICY_VERSION,
                confidence=1.0,
                created_at=event.occurred_at,
            ),
        )

    def derive_working_records(
        self,
        *,
        observation: ObservationSnapshot,
        event: InboundEvent,
    ) -> tuple[MemoryRecord, ...]:
        return tuple(
            self._record(
                category=MemoryCategory.WORKING,
                scope_id=f"conversation:{observation.conversation_id}",
                source_type="conversation_buffer_event",
                source_id=message.event_id,
                summary=(message.content or f"Conversation event {message.event_id}")[:4096],
                confidence=1.0,
                status=MemoryValidationStatus.OBSERVED,
                importance=0.8,
                event=event,
                source_event_ids=(message.event_id,),
                created_at=message.occurred_at,
                provenance=Provenance(
                    kind=ProvenanceKind.RULE,
                    source_id=message.event_id,
                    method="conversation-buffer-projection-v1",
                    confidence=1.0,
                    created_at=message.occurred_at,
                ),
            )
            for message in observation.recent_messages
        )

    def build_write_set(
        self,
        *,
        event: InboundEvent,
        self_model: SelfModel,
        social: SocialTransition,
        beliefs: BeliefTransition,
        goals: GoalTransition,
    ) -> MemoryWriteSet:
        records = [
            self._record(
                category=MemoryCategory.EPISODIC,
                scope_id=f"conversation:{event.conversation_id}",
                source_type="inbound_event",
                source_id=event.event_id,
                summary=f"Actor {event.actor_id} sent an event in {event.conversation_id}.",
                confidence=1.0,
                status=MemoryValidationStatus.OBSERVED,
                importance=0.4,
                event=event,
            ),
            self._record(
                category=MemoryCategory.SOCIAL,
                scope_id=f"actor:{social.after.relationship_id}",
                source_type="social_relationship",
                source_id=social.after.relationship_id,
                summary="Canonical relationship state reference.",
                confidence=1.0,
                status=MemoryValidationStatus.OBSERVED,
                importance=0.5,
                event=event,
                provenance=social.delta.provenance,
            ),
            self._record(
                category=MemoryCategory.AUTOBIOGRAPHICAL,
                scope_id=f"persona:{self_model.persona_id}",
                source_type="self_model",
                source_id=self_model.identity_fingerprint,
                summary="Canonical self-model identity reference.",
                confidence=1.0,
                status=MemoryValidationStatus.VALIDATED,
                importance=1.0,
                event=event,
                source_event_ids=(),
                provenance=Provenance(
                    kind=ProvenanceKind.RULE,
                    source_id=self_model.identity_fingerprint,
                    method=self_model.model_version,
                    confidence=1.0,
                    created_at=event.occurred_at,
                ),
            ),
            self._record(
                category=MemoryCategory.PROCEDURAL,
                scope_id=f"persona:{self_model.persona_id}",
                source_type="policy",
                source_id=MEMORY_AWARE_ACTION_POLICY_VERSION,
                summary="Canonical action-selection procedure reference.",
                confidence=1.0,
                status=MemoryValidationStatus.VALIDATED,
                importance=0.7,
                event=event,
                source_event_ids=(),
                provenance=Provenance(
                    kind=ProvenanceKind.RULE,
                    source_id=MEMORY_AWARE_ACTION_POLICY_VERSION,
                    method=MEMORY_AWARE_ACTION_POLICY_VERSION,
                    confidence=1.0,
                    created_at=event.occurred_at,
                ),
            ),
        ]
        for belief in beliefs.upserts:
            model_evidence = next(
                (
                    evidence.provenance
                    for evidence in belief.evidence
                    if evidence.provenance.kind is ProvenanceKind.MODEL
                ),
                None,
            )
            records.append(
                self._record(
                    category=MemoryCategory.SEMANTIC,
                    scope_id=f"actor:{belief.scope_id}",
                    source_type="belief",
                    source_id=belief.belief_id,
                    summary="Canonical belief reference.",
                    confidence=belief.confidence,
                    status=(
                        MemoryValidationStatus.VALIDATED
                        if belief.status.value == "accepted" and model_evidence is None
                        else MemoryValidationStatus.PROVISIONAL
                    ),
                    importance=0.6,
                    event=event,
                    source_event_ids=tuple(
                        dict.fromkeys(evidence.event_id for evidence in belief.evidence)
                    ),
                    provenance=model_evidence or belief.provenance,
                )
            )
        changed_goal_ids = {change.goal_id for change in goals.changes}
        for goal in goals.after:
            if goal.goal_id not in changed_goal_ids:
                continue
            records.append(
                self._record(
                    category=MemoryCategory.COMMITMENT,
                    scope_id=f"persona:{goal.owner}",
                    source_type="goal",
                    source_id=goal.goal_id,
                    summary="Canonical goal and commitment reference.",
                    confidence=goal.provenance.confidence,
                    status=MemoryValidationStatus.OBSERVED,
                    importance=goal.priority,
                    event=event,
                    source_event_ids=(goal.provenance.source_id,),
                    provenance=goal.provenance,
                )
            )
        unique = {record.memory_id: record for record in records}
        return MemoryWriteSet(
            policy_version=MEMORY_POLICY_VERSION,
            records=tuple(sorted(unique.values(), key=lambda record: record.memory_id)),
            reason_codes=(
                "working_memory_uses_conversation_buffer",
                "canonical_records_are_referenced_not_duplicated",
                "vector_projection_not_enabled",
            ),
        )

    @staticmethod
    def _record(
        *,
        category: MemoryCategory,
        scope_id: str,
        source_type: str,
        source_id: str,
        summary: str,
        confidence: float,
        status: MemoryValidationStatus,
        importance: float,
        event: InboundEvent,
        source_event_ids: tuple[str, ...] | None = None,
        created_at: datetime | None = None,
        provenance: Provenance | None = None,
    ) -> MemoryRecord:
        record_created_at = event.occurred_at if created_at is None else created_at
        material = f"{category.value}\x1f{source_type}\x1f{source_id}"
        memory_id = f"memory:{hashlib.sha256(material.encode()).hexdigest()[:24]}"
        return MemoryRecord(
            memory_id=memory_id,
            category=category,
            scope_id=scope_id,
            canonical_source_type=source_type,
            canonical_source_id=source_id,
            summary=summary,
            confidence=confidence,
            validation_status=status,
            importance=importance,
            source_event_ids=(
                source_event_ids if source_event_ids is not None else (event.event_id,)
            ),
            provenance=provenance
            or Provenance(
                kind=ProvenanceKind.RULE,
                source_id=event.event_id,
                method=MEMORY_POLICY_VERSION,
                confidence=1.0,
                created_at=event.occurred_at,
            ),
            created_at=record_created_at,
            updated_at=max(event.occurred_at, record_created_at),
        )


class MemoryRetrievalPolicy:
    def retrieve(
        self,
        *,
        query: MemoryQuery,
        candidates: tuple[MemoryRecord, ...],
        event: InboundEvent,
    ) -> MemoryRetrievalResult:
        items: list[MemoryRetrievalItem] = []
        category_weights = {item.category: item.weight for item in query.category_weights}
        for memory in candidates:
            if memory.scope_id not in query.scope_ids:
                continue
            if memory.category not in query.categories:
                continue
            if memory.validation_status is MemoryValidationStatus.REJECTED:
                continue
            validation_bonus = {
                MemoryValidationStatus.VALIDATED: 0.2,
                MemoryValidationStatus.OBSERVED: 0.15,
                MemoryValidationStatus.PROVISIONAL: 0.0,
                MemoryValidationStatus.REJECTED: -0.5,
            }[memory.validation_status]
            score = max(
                0.0,
                min(
                    1.0,
                    memory.importance * 0.45
                    + memory.confidence * 0.2
                    + category_weights[memory.category] * 0.15
                    + validation_bonus,
                ),
            )
            items.append(
                MemoryRetrievalItem(
                    memory=memory,
                    score=round(score, 6),
                    reason_codes=(
                        "scope_match",
                        "category_match",
                        f"validation:{memory.validation_status.value}",
                        f"category_weight:{category_weights[memory.category]:.6f}",
                    ),
                    provenance=Provenance(
                        kind=ProvenanceKind.RULE,
                        source_id=memory.memory_id,
                        method=RETRIEVAL_POLICY_VERSION,
                        confidence=1.0,
                        created_at=event.occurred_at,
                    ),
                )
            )
        ranked = tuple(
            sorted(
                items,
                key=lambda item: (-item.score, item.memory.memory_id),
            )[: query.limit]
        )
        return MemoryRetrievalResult(
            policy_version=RETRIEVAL_POLICY_VERSION,
            query=query,
            items=ranked,
            vector_index_used=False,
        )


class OutcomePolicy:
    def evaluate(
        self,
        *,
        cycle_id: str,
        event: InboundEvent,
        selected_action: OutboundAction | None,
        execution: ExecutionResult | None,
        goals: GoalTransition,
        social: SocialTransition,
        internal: InternalTransition,
    ) -> OutcomeEvaluation:
        if selected_action is None:
            status = OutcomeStatus.NO_ACTION
            observed = "No external action was selected."
            prediction_error = 0.0
        elif execution is not None and execution.status is ExecutionStatus.FAILED:
            status = OutcomeStatus.FAILED
            observed = execution.error_code or "execution_failed"
            prediction_error = 1.0
        elif execution is not None and execution.status is ExecutionStatus.SUCCEEDED:
            status = OutcomeStatus.SUCCEEDED
            observed = "External action succeeded."
            prediction_error = 0.0
        else:
            status = OutcomeStatus.SIMULATED
            observed = "Action execution was simulated."
            prediction_error = 0.2
        goal_progress = max(
            (goal.progress for goal in goals.after),
            default=0.0,
        )
        return OutcomeEvaluation(
            policy_version=OUTCOME_POLICY_VERSION,
            cycle_id=cycle_id,
            status=status,
            expected_outcome=(
                "Selected action executes without violating constraints."
                if selected_action is not None
                else "No external side effect."
            ),
            observed_outcome=observed,
            goal_progress=goal_progress,
            social_effect=round(
                max(
                    -1.0,
                    min(1.0, social.delta.trust_delta - social.delta.tension_delta),
                ),
                6,
            ),
            drive_satisfaction=round(
                max(
                    -1.0,
                    min(
                        1.0,
                        internal.delta.drives.curiosity
                        - internal.delta.drives.safety
                        - internal.delta.drives.uncertainty_reduction,
                    ),
                ),
                6,
            ),
            prediction_error=prediction_error,
            reason_codes=(f"outcome:{status.value}",),
            provenance=Provenance(
                kind=ProvenanceKind.INTERNAL,
                source_id=event.event_id,
                method=OUTCOME_POLICY_VERSION,
                confidence=1.0,
                created_at=event.occurred_at,
            ),
        )


class LearningPolicy:
    def propose(
        self,
        *,
        event: InboundEvent,
        outcome: OutcomeEvaluation,
        beliefs: BeliefTransition,
        social: SocialTransition,
        internal: InternalTransition | None = None,
    ) -> tuple[tuple[LearningProposal, ...], tuple[ReflectionTrigger, ...]]:
        proposals: list[LearningProposal] = []
        triggers: list[ReflectionTrigger] = []
        learning_strength = self.learning_strength(internal)
        modulation_reasons = (
            ("internal_affect_modulates_learning_strength",) if internal is not None else ()
        )

        contested = [belief for belief in beliefs.upserts if belief.status.value == "contested"]
        if contested:
            proposal = self._proposal(
                event=event,
                target=LearningTarget.BELIEF,
                target_id=contested[0].belief_id,
                change="Review contradictory evidence before changing belief status.",
                evidence_ids=tuple(belief.belief_id for belief in contested),
                confidence=0.8,
                learning_strength=learning_strength,
                reason_codes=modulation_reasons,
            )
            proposals.append(proposal)
            triggers.append(
                self._trigger(
                    event=event,
                    trigger_type=ReflectionTriggerType.BELIEF_CONFLICT,
                    severity=0.7,
                    evidence_ids=proposal.evidence_ids,
                )
            )
        if outcome.status is OutcomeStatus.FAILED:
            proposal = self._proposal(
                event=event,
                target=LearningTarget.STRATEGY,
                target_id="strategy:execution",
                change="Review execution strategy; do not mutate the executor automatically.",
                evidence_ids=(event.event_id,),
                confidence=0.9,
                learning_strength=learning_strength,
                reason_codes=modulation_reasons,
            )
            proposals.append(proposal)
            triggers.append(
                self._trigger(
                    event=event,
                    trigger_type=ReflectionTriggerType.EXECUTION_FAILURE,
                    severity=0.9,
                    evidence_ids=(event.event_id,),
                )
            )
            proposals.append(
                self._proposal(
                    event=event,
                    target=LearningTarget.RETRIEVAL_WEIGHT,
                    target_id="retrieval:execution-context",
                    change=(
                        "Review whether execution-context retrieval weights contributed "
                        "to the prediction error."
                    ),
                    evidence_ids=(event.event_id,),
                    confidence=0.65,
                    learning_strength=learning_strength,
                    reason_codes=modulation_reasons,
                )
            )
        if social.delta.boundary_violations_delta > 0:
            proposal = self._proposal(
                event=event,
                target=LearningTarget.RELATIONSHIP,
                target_id=social.after.relationship_id,
                change="Review boundary evidence before any durable relationship adjustment.",
                evidence_ids=(event.event_id,),
                confidence=0.85,
                learning_strength=learning_strength,
                reason_codes=modulation_reasons,
            )
            proposals.append(proposal)
            triggers.append(
                self._trigger(
                    event=event,
                    trigger_type=ReflectionTriggerType.RELATIONSHIP_CHANGE,
                    severity=0.6,
                    evidence_ids=(event.event_id,),
                )
            )
        return tuple(proposals), tuple(triggers)

    @staticmethod
    def _proposal(
        *,
        event: InboundEvent,
        target: LearningTarget,
        target_id: str,
        change: str,
        evidence_ids: tuple[str, ...],
        confidence: float,
        learning_strength: float,
        reason_codes: tuple[str, ...],
    ) -> LearningProposal:
        material = f"{event.event_id}\x1f{target.value}\x1f{target_id}"
        proposal_id = f"proposal:{hashlib.sha256(material.encode()).hexdigest()[:24]}"
        return LearningProposal(
            proposal_id=proposal_id,
            target=target,
            target_id=target_id,
            proposed_change=change,
            evidence_ids=evidence_ids,
            confidence=round(min(1.0, confidence * learning_strength), 6),
            reason_codes=reason_codes,
            status=ProposalStatus.PENDING_VALIDATION,
            requires_validation=True,
            provenance=Provenance(
                kind=ProvenanceKind.RULE,
                source_id=event.event_id,
                method=LEARNING_POLICY_VERSION,
                confidence=1.0,
                created_at=event.occurred_at,
            ),
        )

    @staticmethod
    def learning_strength(internal: InternalTransition | None) -> float:
        if internal is None:
            return 1.0
        affect = internal.after.affect
        return round(
            max(
                0.75,
                min(
                    1.10,
                    0.75
                    + affect.arousal * 0.10
                    + affect.frustration * 0.15
                    + affect.uncertainty * 0.10,
                ),
            ),
            6,
        )

    @staticmethod
    def _trigger(
        *,
        event: InboundEvent,
        trigger_type: ReflectionTriggerType,
        severity: float,
        evidence_ids: tuple[str, ...],
    ) -> ReflectionTrigger:
        material = f"{event.event_id}\x1f{trigger_type.value}"
        trigger_id = f"reflection:{hashlib.sha256(material.encode()).hexdigest()[:24]}"
        return ReflectionTrigger(
            trigger_id=trigger_id,
            trigger_type=trigger_type,
            severity=severity,
            reason_codes=(f"trigger:{trigger_type.value}",),
            evidence_ids=evidence_ids,
            requires_validation=True,
        )
