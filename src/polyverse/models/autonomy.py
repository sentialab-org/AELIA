from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from polyverse.contracts.actions import RiskClass
from polyverse.contracts.common import NonEmptyId, Provenance, StrictModel


class AutonomyMode(StrEnum):
    DISABLED = "disabled"
    SHADOW = "shadow"


class InternalTriggerType(StrEnum):
    COMMITMENT_DUE = "commitment_due"
    DEADLINE_DUE = "deadline_due"
    UNRESOLVED_QUESTION = "unresolved_question"
    RESULT_AVAILABLE = "result_available"
    HIGH_DRIVE_PRESSURE = "high_drive_pressure"


class InitiativeType(StrEnum):
    FOLLOW_UP = "follow_up"
    REMIND = "remind"
    SHARE_RESULT = "share_result"
    SEEK_INFORMATION = "seek_information"


class GuardrailOutcome(StrEnum):
    BLOCKED = "blocked"
    REQUIRE_CONFIRMATION = "require_confirmation"
    SHADOW_APPROVED = "shadow_approved"


class OptOutScope(StrEnum):
    ACTOR = "actor"
    CONVERSATION = "conversation"


class AutonomyPolicyConfig(StrictModel):
    policy_version: str
    mode: AutonomyMode
    timezone: str
    quiet_hours_enabled: bool
    quiet_start_hour: Annotated[int, Field(ge=0, le=23)]
    quiet_end_hour: Annotated[int, Field(ge=0, le=23)]
    actor_limit_per_hour: Annotated[int, Field(ge=1, le=1_000)]
    conversation_limit_per_hour: Annotated[int, Field(ge=1, le=10_000)]
    daily_cost_budget: Annotated[float, Field(gt=0.0, le=1_000_000.0)]
    minimum_expected_value: Annotated[float, Field(ge=0.0, le=1.0)]
    high_drive_threshold: Annotated[float, Field(ge=0.0, le=1.0)]

    @field_validator("timezone")
    @classmethod
    def require_valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("autonomy policy timezone must be a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def validate_quiet_hours(self) -> AutonomyPolicyConfig:
        if self.quiet_hours_enabled and self.quiet_start_hour == self.quiet_end_hour:
            raise ValueError("enabled quiet hours require distinct start and end")
        return self


class AutonomyRuntimeState(StrictModel):
    actor_id: NonEmptyId
    conversation_id: NonEmptyId
    actor_opted_out: bool
    conversation_opted_out: bool
    actor_shadow_actions_last_hour: Annotated[int, Field(ge=0)]
    conversation_shadow_actions_last_hour: Annotated[int, Field(ge=0)]
    daily_shadow_cost_used: Annotated[float, Field(ge=0.0)]
    evidence_audit_ids: tuple[NonEmptyId, ...]


class InternalTrigger(StrictModel):
    trigger_id: NonEmptyId
    trigger_type: InternalTriggerType
    source_event_id: NonEmptyId
    source_type: Annotated[str, Field(min_length=1, max_length=128)]
    source_id: NonEmptyId
    target_actor_id: NonEmptyId
    target_conversation_id: NonEmptyId
    urgency: Annotated[float, Field(ge=0.0, le=1.0)]
    reason_codes: Annotated[tuple[str, ...], Field(min_length=1)]
    provenance: Provenance
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("trigger created_at must include a timezone")
        return value.astimezone(UTC)


class InitiativeProposal(StrictModel):
    proposal_id: NonEmptyId
    trigger_id: NonEmptyId
    initiative_type: InitiativeType
    target_actor_id: NonEmptyId
    target_conversation_id: NonEmptyId
    description: Annotated[str, Field(min_length=1, max_length=2048)]
    expected_value: Annotated[float, Field(ge=0.0, le=1.0)]
    estimated_cost: Annotated[float, Field(ge=0.0)]
    risk_class: RiskClass
    reversible: bool
    required_permission: Annotated[str, Field(min_length=1, max_length=128)]
    privacy_sensitive: bool
    reason_codes: Annotated[tuple[str, ...], Field(min_length=1)]
    provenance: Provenance
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("initiative created_at must include a timezone")
        return value.astimezone(UTC)


class GuardrailCheck(StrictModel):
    code: str
    passed: bool
    observed: str
    limit: str | None = None
    reason_code: str


class GuardrailDecision(StrictModel):
    decision_id: NonEmptyId
    proposal_id: NonEmptyId
    outcome: GuardrailOutcome
    checks: Annotated[tuple[GuardrailCheck, ...], Field(min_length=1)]
    reason_codes: Annotated[tuple[str, ...], Field(min_length=1)]
    confirmation_scope: str | None
    policy_version: str
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("guardrail evaluated_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_outcome(self) -> GuardrailDecision:
        check_codes = [check.code for check in self.checks]
        if len(check_codes) != len(set(check_codes)):
            raise ValueError("guardrail check codes must be unique")
        failed = [check for check in self.checks if not check.passed]
        confirmation_failures = [check for check in failed if check.code == "confirmation"]
        blocking_failures = [check for check in failed if check.code != "confirmation"]
        if self.outcome is GuardrailOutcome.BLOCKED and not blocking_failures:
            raise ValueError("blocked guardrail decision requires a blocking failure")
        if self.outcome is GuardrailOutcome.REQUIRE_CONFIRMATION and (
            blocking_failures or len(confirmation_failures) != 1
        ):
            raise ValueError("confirmation outcome requires only an unmet confirmation check")
        if self.outcome is GuardrailOutcome.SHADOW_APPROVED and failed:
            raise ValueError("shadow-approved guardrail decision requires all checks to pass")
        return self


class AutonomyAuditRecord(StrictModel):
    audit_id: NonEmptyId
    cycle_id: NonEmptyId
    source_event_id: NonEmptyId
    trigger_id: NonEmptyId
    proposal_id: NonEmptyId
    decision_id: NonEmptyId
    target_actor_id: NonEmptyId
    target_conversation_id: NonEmptyId
    outcome: GuardrailOutcome
    estimated_cost: Annotated[float, Field(ge=0.0)]
    proactive_action_materialized: Literal[False]
    reason_codes: Annotated[tuple[str, ...], Field(min_length=1)]
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit recorded_at must include a timezone")
        return value.astimezone(UTC)


class AutonomyEvaluation(StrictModel):
    policy_version: str
    config: AutonomyPolicyConfig
    runtime_state: AutonomyRuntimeState
    triggers: tuple[InternalTrigger, ...]
    proposals: tuple[InitiativeProposal, ...]
    decisions: tuple[GuardrailDecision, ...]
    audit_records: tuple[AutonomyAuditRecord, ...]
    proactive_action_materialized: Literal[False]

    @model_validator(mode="after")
    def validate_causal_links(self) -> AutonomyEvaluation:
        trigger_ids = {trigger.trigger_id for trigger in self.triggers}
        proposal_ids = {proposal.proposal_id for proposal in self.proposals}
        decision_ids = {decision.decision_id for decision in self.decisions}
        if len(trigger_ids) != len(self.triggers):
            raise ValueError("autonomy trigger ids must be unique")
        if len(proposal_ids) != len(self.proposals):
            raise ValueError("initiative proposal ids must be unique")
        if len(decision_ids) != len(self.decisions):
            raise ValueError("guardrail decision ids must be unique")
        if any(proposal.trigger_id not in trigger_ids for proposal in self.proposals):
            raise ValueError("initiative proposal must reference an originating trigger")
        if any(
            proposal.target_actor_id != self.runtime_state.actor_id
            or proposal.target_conversation_id != self.runtime_state.conversation_id
            for proposal in self.proposals
        ):
            raise ValueError("initiative proposal target must match runtime guardrail state")
        if {decision.proposal_id for decision in self.decisions} != proposal_ids:
            raise ValueError("each initiative proposal requires one guardrail decision")
        if len(self.decisions) != len(self.proposals):
            raise ValueError("each initiative proposal requires exactly one decision")
        if len(self.audit_records) != len(self.decisions):
            raise ValueError("each guardrail decision requires one audit record")
        proposals_by_id = {proposal.proposal_id: proposal for proposal in self.proposals}
        decisions_by_id = {decision.decision_id: decision for decision in self.decisions}
        for audit in self.audit_records:
            decision = decisions_by_id.get(audit.decision_id)
            proposal = proposals_by_id.get(audit.proposal_id)
            if (
                decision is None
                or proposal is None
                or decision.proposal_id != audit.proposal_id
                or proposal.trigger_id != audit.trigger_id
                or decision.outcome is not audit.outcome
                or audit.proactive_action_materialized
            ):
                raise ValueError("autonomy audit record has invalid causal references")
        return self
