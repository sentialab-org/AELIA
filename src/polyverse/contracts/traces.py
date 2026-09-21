from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from polyverse.contracts.actions import (
    ActionSelection,
    DeliberationResult,
    ExecutionResult,
    ExecutionStatus,
    LanguageGenerationResult,
    LanguageGenerationStatus,
    OutboundAction,
    TurnTakingDecision,
)
from polyverse.contracts.common import NonEmptyId, StrictModel
from polyverse.contracts.observation import ObservationSnapshot
from polyverse.contracts.participation import AttentionResult, ParticipationDecision
from polyverse.models.autonomy import AutonomyEvaluation
from polyverse.models.belief import BeliefTransition
from polyverse.models.cognition import AppraisalResult, InternalTransition
from polyverse.models.conversation import ConversationModel
from polyverse.models.goals import GoalTransition
from polyverse.models.memory import (
    LearningProposal,
    MemoryRetrievalResult,
    MemoryWriteSet,
    OutcomeEvaluation,
    ProposalStatus,
    ReflectionTrigger,
)
from polyverse.models.perception import PerceptionResult
from polyverse.models.self_model import SelfModel
from polyverse.models.social import SocialTransition
from polyverse.models.world import WorldModel
from polyverse.persona.models import DisclosureEvaluation, PersonaView

TraceSchemaVersion = Literal["2.1.0", "2.2.0", "2.3.0"]
CURRENT_TRACE_SCHEMA_VERSION: TraceSchemaVersion = "2.3.0"


class CycleStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class FoundationDecision(StrictModel):
    outcome: Literal["observe"]
    reason_codes: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...]
    policy_version: Annotated[str, Field(min_length=1, max_length=64)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]


class CycleError(StrictModel):
    code: Annotated[str, Field(min_length=1, max_length=128)]
    message: Annotated[str, Field(min_length=1, max_length=2048)]
    retryable: bool


class CycleRetry(StrictModel):
    attempt: Annotated[int, Field(ge=1)]
    component: Annotated[str, Field(min_length=1, max_length=128)]
    code: Annotated[str, Field(min_length=1, max_length=128)]
    message: Annotated[str, Field(min_length=1, max_length=2048)]
    retryable: Literal[True] = True


class CycleTrace(StrictModel):
    schema_version: TraceSchemaVersion
    cycle_id: NonEmptyId
    event_id: NonEmptyId
    orchestrator_version: Annotated[str, Field(min_length=1, max_length=64)]
    started_at: datetime
    completed_at: datetime
    status: CycleStatus
    state_version_before: Annotated[int, Field(ge=0)]
    state_version_after: Annotated[int, Field(ge=0)]
    attention: AttentionResult | None = None
    observation: ObservationSnapshot | None = None
    conversation_model: ConversationModel | None = None
    self_model: SelfModel | None = None
    social_transition: SocialTransition | None = None
    persona_view: PersonaView | None = None
    disclosure: DisclosureEvaluation | None = None
    perception: PerceptionResult | None = None
    belief_transition: BeliefTransition | None = None
    world_model: WorldModel | None = None
    appraisal: AppraisalResult | None = None
    internal_transition: InternalTransition | None = None
    goal_transition: GoalTransition | None = None
    deliberation: DeliberationResult | None = None
    action_selection: ActionSelection | None = None
    turn_taking: TurnTakingDecision | None = None
    decision: FoundationDecision | ParticipationDecision
    selected_action: OutboundAction | None = None
    language_generation: LanguageGenerationResult | None = None
    execution_result: ExecutionResult | None = None
    memory_retrieval: MemoryRetrievalResult | None = None
    memory_write_set: MemoryWriteSet | None = None
    outcome_evaluation: OutcomeEvaluation | None = None
    learning_proposals: tuple[LearningProposal, ...] = ()
    reflection_triggers: tuple[ReflectionTrigger, ...] = ()
    autonomy_evaluation: AutonomyEvaluation | None = None
    errors: tuple[CycleError, ...] = ()
    retries: tuple[CycleRetry, ...] = ()

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cycle timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_timeline(self) -> CycleTrace:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not be earlier than started_at")
        if self.status is CycleStatus.COMPLETED and self.errors:
            raise ValueError("completed cycles cannot contain errors")
        if self.status is CycleStatus.FAILED and not self.errors:
            raise ValueError("failed cycles require at least one structured error")
        if (
            self.schema_version in {"2.2.0", "2.3.0"}
            and self.execution_result is not None
            and self.execution_result.status is ExecutionStatus.FAILED
        ):
            if self.status is not CycleStatus.FAILED:
                raise ValueError("failed execution requires a failed cycle")
            if not any(error.code == self.execution_result.error_code for error in self.errors):
                raise ValueError("failed execution error must be represented in cycle errors")
        retry_attempts = [retry.attempt for retry in self.retries]
        if retry_attempts != list(range(1, len(retry_attempts) + 1)):
            raise ValueError("cycle retries must use contiguous attempts starting at one")
        if self.schema_version == "2.1.0" and self.retries:
            raise ValueError("trace schema 2.1.0 cannot contain retry history")
        if isinstance(self.decision, ParticipationDecision):
            if self.decision.cycle_id != self.cycle_id:
                raise ValueError("participation decision cycle_id must match trace")
            if self.attention is None or self.observation is None:
                raise ValueError("participation cycles require attention and observation")
            if self.state_version_before != self.observation.state_version:
                raise ValueError("observation state version must match cycle state version")
            if self.state_version_after != self.state_version_before + 1:
                raise ValueError("participation cycles must advance state by exactly one")
            if (
                self.decision.outcome.value in {"reply", "join"}
                and self.selected_action is None
                and self.action_selection is None
            ):
                raise ValueError("communicative decisions require a selected action")
            if (
                self.decision.outcome.value not in {"reply", "join"}
                and self.selected_action is not None
            ):
                raise ValueError("non-communicative decisions cannot select an outbound action")
            if self.conversation_model is not None:
                if self.conversation_model.conversation_id != self.observation.conversation_id:
                    raise ValueError("conversation model and observation ids must match")
                if self.conversation_model.based_on_state_version != self.observation.state_version:
                    raise ValueError(
                        "conversation model must be based on the observed state version"
                    )
                if self.conversation_model.latest_event_id != self.event_id:
                    raise ValueError("conversation model must include the current event")
            if self.selected_action is not None:
                if self.selected_action.cycle_id != self.cycle_id:
                    raise ValueError("selected action cycle_id must match trace")
                if self.selected_action.action_type.value != self.decision.outcome.value:
                    raise ValueError(
                        "selected action type must match the communicative participation outcome"
                    )
                if self.execution_result is None:
                    raise ValueError("selected actions require an execution result")
                if self.execution_result.action_id != self.selected_action.action_id:
                    raise ValueError("execution result action_id must match selected action")
                if self.language_generation is not None:
                    if self.language_generation.action_id != self.selected_action.action_id:
                        raise ValueError("language generation action_id must match selected action")
                    if self.language_generation.changed_participation:
                        raise ValueError("language generation cannot change participation")
                    if (
                        self.language_generation.selected_action_type
                        is not self.selected_action.action_type
                    ):
                        raise ValueError("language generation cannot change selected action type")
                    if (
                        self.schema_version == "2.3.0"
                        and self.language_generation.status is LanguageGenerationStatus.FAILED
                    ):
                        if self.status is not CycleStatus.FAILED:
                            raise ValueError("failed language generation requires a failed cycle")
                        if (
                            self.execution_result.status is not ExecutionStatus.FAILED
                            or self.execution_result.error_code
                            != self.language_generation.error_code
                        ):
                            raise ValueError(
                                "failed language generation requires a matching failed execution"
                            )
        persona_artifacts = (
            self.self_model,
            self.social_transition,
            self.persona_view,
            self.disclosure,
        )
        if any(artifact is not None for artifact in persona_artifacts) and not all(
            artifact is not None for artifact in persona_artifacts
        ):
            raise ValueError("persona cycles require self, social, view, and disclosure artifacts")
        if self.self_model is not None and self.persona_view is not None:
            if self.self_model.persona_id != self.persona_view.persona_id:
                raise ValueError("self model and persona view persona ids must match")
            if (
                self.self_model.persona_specification_version
                != self.persona_view.specification_version
            ):
                raise ValueError("self model and persona view specification versions must match")
        cognitive_artifacts = (
            self.perception,
            self.belief_transition,
            self.appraisal,
            self.internal_transition,
        )
        if any(artifact is not None for artifact in cognitive_artifacts) and not all(
            artifact is not None for artifact in cognitive_artifacts
        ):
            raise ValueError(
                "cognitive cycles require perception, belief, appraisal, and internal artifacts"
            )
        if self.world_model is not None:
            if self.perception is None or self.belief_transition is None:
                raise ValueError("world model requires perception and belief artifacts")
            if self.world_model.current_event_id != self.event_id:
                raise ValueError("world model must include the current event")
        action_policy_artifacts = (
            self.goal_transition,
            self.deliberation,
            self.action_selection,
            self.turn_taking,
        )
        if any(artifact is not None for artifact in action_policy_artifacts) and not all(
            artifact is not None for artifact in action_policy_artifacts
        ):
            raise ValueError(
                "action-policy cycles require goal, deliberation, selection, and turn-taking"
            )
        memory_artifacts = (
            self.memory_retrieval,
            self.memory_write_set,
            self.outcome_evaluation,
        )
        if any(artifact is not None for artifact in memory_artifacts) and not all(
            artifact is not None for artifact in memory_artifacts
        ):
            raise ValueError("memory cycles require retrieval, write-set, and outcome artifacts")
        if self.outcome_evaluation is not None:
            if self.outcome_evaluation.cycle_id != self.cycle_id:
                raise ValueError("outcome evaluation cycle_id must match trace")
            if any(
                proposal.status is not ProposalStatus.PENDING_VALIDATION
                or not proposal.requires_validation
                for proposal in self.learning_proposals
            ):
                raise ValueError("cycle learning proposals must await validation")
        elif self.learning_proposals or self.reflection_triggers:
            raise ValueError("learning and reflection require an outcome evaluation")
        if self.autonomy_evaluation is not None:
            if self.outcome_evaluation is None:
                raise ValueError("autonomy evaluation requires an M6 outcome")
            if any(
                audit.cycle_id != self.cycle_id or audit.source_event_id != self.event_id
                for audit in self.autonomy_evaluation.audit_records
            ):
                raise ValueError("autonomy audit must belong to the current cycle and event")
        return self
