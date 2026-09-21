from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from polyverse.contracts.common import NonEmptyId, StrictModel
from polyverse.models.prompt import PromptComposition

ActionSchemaVersion = Literal["2.1.0", "2.2.0"]
CURRENT_ACTION_SCHEMA_VERSION: ActionSchemaVersion = "2.2.0"


class ActionType(StrEnum):
    REPLY = "reply"
    JOIN = "join"


class RiskClass(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContentPlan(StrictModel):
    intent: Annotated[str, Field(min_length=1, max_length=256)]
    constraints: tuple[Annotated[str, Field(min_length=1, max_length=256)], ...]
    prohibited_traits: tuple[Annotated[str, Field(min_length=1, max_length=256)], ...]
    generator: Annotated[str, Field(min_length=1, max_length=128)]
    prompt: PromptComposition | None = None


class ActionTarget(StrictModel):
    conversation_id: NonEmptyId
    reply_to_event_id: NonEmptyId | None = None


class OutboundAction(StrictModel):
    schema_version: ActionSchemaVersion
    action_id: NonEmptyId
    cycle_id: NonEmptyId
    action_type: ActionType
    target: ActionTarget
    content_plan: ContentPlan
    permission_scope: Annotated[str, Field(min_length=1, max_length=128)]
    idempotency_key: NonEmptyId
    risk_class: RiskClass
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_target_semantics(self) -> OutboundAction:
        if self.schema_version == "2.2.0" and self.content_plan.prompt is None:
            raise ValueError("action schema 2.2.0 requires prompt composition metadata")
        if self.schema_version == "2.1.0" and self.content_plan.prompt is not None:
            raise ValueError("action schema 2.1.0 cannot contain prompt composition metadata")
        if self.action_type is ActionType.REPLY and self.target.reply_to_event_id is None:
            raise ValueError("reply action requires reply_to_event_id")
        if self.action_type is ActionType.JOIN and self.target.reply_to_event_id is not None:
            raise ValueError("join action cannot target a specific event")
        return self


class ExecutionStatus(StrEnum):
    SIMULATED = "simulated"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ExecutionResult(StrictModel):
    action_id: NonEmptyId
    status: ExecutionStatus
    executor: Annotated[str, Field(min_length=1, max_length=128)]
    side_effect_performed: bool
    error_code: Annotated[str | None, Field(max_length=128)] = None
    error_message: Annotated[str | None, Field(max_length=2048)] = None
    retryable: bool = False

    @model_validator(mode="after")
    def validate_failure_details(self) -> ExecutionResult:
        if self.status is ExecutionStatus.FAILED and self.error_code is None:
            raise ValueError("failed execution requires error_code")
        if self.status is not ExecutionStatus.FAILED and (
            self.error_code is not None or self.error_message is not None
        ):
            raise ValueError("successful/simulated execution cannot contain an error")
        if self.status is ExecutionStatus.FAILED and self.side_effect_performed:
            raise ValueError("failed execution cannot report a performed side effect")
        return self


class CandidateActionType(StrEnum):
    NO_ACTION = "no_action"
    OBSERVE = "observe"
    SILENT = "silent"
    WAIT = "wait"
    REPLY = "reply"
    JOIN = "join"


class ActionCandidate(StrictModel):
    candidate_id: NonEmptyId
    action_type: CandidateActionType
    target: ActionTarget
    expected_utility: Annotated[float, Field(ge=0.0, le=1.0)]
    risk: Annotated[float, Field(ge=0.0, le=1.0)]
    cost: Annotated[float, Field(ge=0.0, le=1.0)]
    reversibility: Annotated[float, Field(ge=0.0, le=1.0)]
    social_impact: Annotated[float, Field(ge=-1.0, le=1.0)]
    privacy_impact: Annotated[float, Field(ge=0.0, le=1.0)]
    goal_fit: Annotated[float, Field(ge=0.0, le=1.0)]
    drive_effect: Annotated[float, Field(ge=-1.0, le=1.0)]
    value_fit: Annotated[float, Field(ge=-1.0, le=1.0)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    required_permission: Annotated[str | None, Field(max_length=128)] = None
    explanation: Annotated[str, Field(min_length=1, max_length=2048)]


class DeliberationResult(StrictModel):
    policy_version: str
    candidates: Annotated[tuple[ActionCandidate, ...], Field(min_length=1)]
    proposer: str
    model_proposals_enabled: bool

    @model_validator(mode="after")
    def validate_candidate_ids(self) -> DeliberationResult:
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("deliberation candidate ids must be unique")
        return self


class CandidateScoreBreakdown(StrictModel):
    candidate_id: NonEmptyId
    eligible: bool
    utility: float
    goal_fit: float
    drive_effect: float
    value_fit: float
    relationship_effect: float
    reversibility: float
    confidence: float
    risk_penalty: float
    cost_penalty: float
    privacy_penalty: float
    interruption_penalty: float
    total: float
    reason_codes: tuple[str, ...]
    memory_support: float = 0.0

    @model_validator(mode="after")
    def validate_total(self) -> CandidateScoreBreakdown:
        if not self.eligible:
            if self.total != -1.0:
                raise ValueError("ineligible candidate score must be -1")
            return self
        calculated = (
            self.utility
            + self.goal_fit
            + self.drive_effect
            + self.value_fit
            + self.relationship_effect
            + self.reversibility
            + self.confidence
            + self.risk_penalty
            + self.cost_penalty
            + self.privacy_penalty
            + self.interruption_penalty
            + self.memory_support
        )
        if abs(calculated - self.total) > 1e-6:
            raise ValueError("candidate score total does not equal its components")
        return self


class ActionSelection(StrictModel):
    policy_version: str
    selected_candidate_id: NonEmptyId | None
    scores: Annotated[tuple[CandidateScoreBreakdown, ...], Field(min_length=1)]
    reason_codes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_selected_candidate(self) -> ActionSelection:
        if self.selected_candidate_id is None:
            return self
        selected = [
            score for score in self.scores if score.candidate_id == self.selected_candidate_id
        ]
        if len(selected) != 1 or not selected[0].eligible:
            raise ValueError("selected candidate must reference one eligible score")
        return self


class TurnTakingOutcome(StrEnum):
    SPEAK_NOW = "speak_now"
    WAIT = "wait"
    NO_SPEECH = "no_speech"


class TurnTakingDecision(StrictModel):
    policy_version: str
    outcome: TurnTakingOutcome
    target_event_id: NonEmptyId | None
    reason_codes: tuple[str, ...]


class LanguageGenerationStatus(StrEnum):
    SKIPPED = "skipped"
    GENERATED = "generated"
    FAILED = "failed"


class LanguageGenerationResult(StrictModel):
    action_id: NonEmptyId
    generator: Annotated[str, Field(min_length=1, max_length=128)]
    status: LanguageGenerationStatus
    content: str | None
    selected_action_type: ActionType
    applied_constraints: tuple[str, ...]
    changed_participation: bool
    provider: Annotated[str, Field(min_length=1, max_length=128)]
    model: Annotated[str | None, Field(max_length=256)] = None
    request_id: Annotated[str | None, Field(max_length=256)] = None
    attempts: Annotated[int, Field(ge=0, le=5)]
    error_code: Annotated[str | None, Field(max_length=128)] = None
    retryable: bool = False

    @model_validator(mode="before")
    @classmethod
    def preserve_legacy_results(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        has_content = bool(str(normalized.get("content") or "").strip())
        normalized.setdefault(
            "status",
            (
                LanguageGenerationStatus.GENERATED
                if has_content
                else LanguageGenerationStatus.SKIPPED
            ),
        )
        normalized.setdefault("provider", "legacy-unrecorded")
        normalized.setdefault("attempts", 1 if has_content else 0)
        return normalized

    @model_validator(mode="after")
    def validate_generation_outcome(self) -> LanguageGenerationResult:
        has_content = self.content is not None and bool(self.content.strip())
        if self.status is LanguageGenerationStatus.GENERATED:
            if not has_content:
                raise ValueError("generated language requires non-blank content")
            if self.error_code is not None or self.retryable:
                raise ValueError("generated language cannot contain failure details")
            if self.attempts < 1:
                raise ValueError("generated language requires at least one attempt")
        elif self.status is LanguageGenerationStatus.FAILED:
            if has_content:
                raise ValueError("failed language generation cannot contain content")
            if self.error_code is None:
                raise ValueError("failed language generation requires error_code")
            if self.attempts < 1:
                raise ValueError("failed language generation requires at least one attempt")
        else:
            if has_content or self.error_code is not None or self.retryable:
                raise ValueError("skipped language generation cannot contain output or failure")
            if self.attempts != 0:
                raise ValueError("skipped language generation must have zero attempts")
        return self
