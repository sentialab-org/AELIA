from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from polyverse.contracts.actions import ActionType, RiskClass
from polyverse.contracts.common import NonEmptyId, StrictModel
from polyverse.contracts.connector import (
    ExternalDeliveryReceipt,
    ExternalReceiptStatus,
)
from polyverse.contracts.events import InboundEvent, Platform

AdapterInboundSchemaVersion = Literal["1.0.0"]
AdapterOutboundSchemaVersion = Literal["1.1.0"]
AdapterReceiptSchemaVersion = Literal["1.1.0"]
CURRENT_ADAPTER_INBOUND_SCHEMA_VERSION: AdapterInboundSchemaVersion = "1.0.0"
CURRENT_ADAPTER_OUTBOUND_SCHEMA_VERSION: AdapterOutboundSchemaVersion = "1.1.0"
CURRENT_ADAPTER_RECEIPT_SCHEMA_VERSION: AdapterReceiptSchemaVersion = "1.1.0"


class AdapterMode(StrEnum):
    SHADOW = "shadow"
    TEST_CANARY = "test_canary"
    EXTERNAL_CANARY = "external_canary"


class DispatchOutcome(StrEnum):
    SUPPRESSED_SHADOW = "suppressed_shadow"
    BLOCKED_NOT_CANARY = "blocked_not_canary"
    BLOCKED_RATE_LIMIT = "blocked_rate_limit"
    BLOCKED_MISSING_CONTENT = "blocked_missing_content"
    SIMULATE_CANARY = "simulate_canary"
    QUEUE_EXTERNAL_CANARY = "queue_external_canary"


class DeliveryStatus(StrEnum):
    SUPPRESSED = "suppressed"
    BLOCKED = "blocked"
    SIMULATED = "simulated"
    FAILED = "failed"


class DispatchState(StrEnum):
    RESERVED = "reserved"
    FINALIZED = "finalized"


class AdapterPolicyConfig(StrictModel):
    policy_version: str
    mode: AdapterMode
    canary_conversation_ids: tuple[NonEmptyId, ...]
    conversation_limit_per_hour: Annotated[int, Field(ge=1, le=10_000)]

    @model_validator(mode="after")
    def validate_canary_scope(self) -> AdapterPolicyConfig:
        if len(self.canary_conversation_ids) != len(set(self.canary_conversation_ids)):
            raise ValueError("canary conversation ids must be unique")
        if (
            self.mode in {AdapterMode.TEST_CANARY, AdapterMode.EXTERNAL_CANARY}
            and not self.canary_conversation_ids
        ):
            raise ValueError("canary mode requires at least one conversation")
        return self


class AdapterInboundEnvelope(StrictModel):
    schema_version: AdapterInboundSchemaVersion
    delivery_id: NonEmptyId
    idempotency_key: NonEmptyId
    adapter_id: NonEmptyId
    received_at: datetime
    event: InboundEvent

    @field_validator("received_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("adapter received_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_source(self) -> AdapterInboundEnvelope:
        if self.event.source_reference.adapter != self.adapter_id:
            raise ValueError("adapter envelope id must match event source adapter")
        return self


class AdapterOutboundCommand(StrictModel):
    schema_version: AdapterOutboundSchemaVersion
    command_id: NonEmptyId
    action_id: NonEmptyId
    cycle_id: NonEmptyId
    platform: Platform
    action_type: ActionType
    target_conversation_id: NonEmptyId
    reply_to_event_id: NonEmptyId | None
    content: Annotated[str | None, Field(max_length=100_000)]
    constraints: tuple[str, ...]
    risk_class: RiskClass
    idempotency_key: NonEmptyId
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("adapter command created_at must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_target_semantics(self) -> AdapterOutboundCommand:
        if self.action_type is ActionType.REPLY and self.reply_to_event_id is None:
            raise ValueError("reply command requires reply_to_event_id")
        if self.action_type is ActionType.JOIN and self.reply_to_event_id is not None:
            raise ValueError("join command cannot target a specific event")
        return self


class AdapterDispatchDecision(StrictModel):
    policy_version: str
    command_id: NonEmptyId
    mode: AdapterMode
    outcome: DispatchOutcome
    recent_conversation_dispatches: Annotated[int, Field(ge=0)]
    conversation_limit_per_hour: Annotated[int, Field(ge=1)]
    reason_codes: Annotated[tuple[str, ...], Field(min_length=1)]
    decided_at: datetime

    @field_validator("decided_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("dispatch decision timestamp must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_routing_outcome(self) -> AdapterDispatchDecision:
        if (
            self.mode is AdapterMode.SHADOW
            and self.outcome is not DispatchOutcome.SUPPRESSED_SHADOW
        ):
            raise ValueError("shadow adapter mode can only suppress dispatch")
        if (
            self.mode is not AdapterMode.SHADOW
            and self.outcome is DispatchOutcome.SUPPRESSED_SHADOW
        ):
            raise ValueError("canary mode cannot emit a shadow outcome")
        if (
            self.outcome is DispatchOutcome.SIMULATE_CANARY
            and self.mode is not AdapterMode.TEST_CANARY
        ):
            raise ValueError("simulated delivery requires test-canary mode")
        if (
            self.outcome is DispatchOutcome.QUEUE_EXTERNAL_CANARY
            and self.mode is not AdapterMode.EXTERNAL_CANARY
        ):
            raise ValueError("external delivery requires external-canary mode")
        if (
            self.outcome
            in {
                DispatchOutcome.SIMULATE_CANARY,
                DispatchOutcome.QUEUE_EXTERNAL_CANARY,
            }
            and self.recent_conversation_dispatches >= self.conversation_limit_per_hour
        ):
            raise ValueError("canary dispatch cannot exceed its rate limit")
        if (
            self.outcome is DispatchOutcome.BLOCKED_RATE_LIMIT
            and self.recent_conversation_dispatches < self.conversation_limit_per_hour
        ):
            raise ValueError("rate-limit block requires an exhausted limit")
        return self


class AdapterDeliveryReceipt(StrictModel):
    schema_version: AdapterReceiptSchemaVersion
    receipt_id: NonEmptyId
    command_id: NonEmptyId
    idempotency_key: NonEmptyId
    status: DeliveryStatus
    transport: NonEmptyId
    side_effect_performed: Literal[False]
    error_code: str | None = None
    retryable: bool = False
    completed_at: datetime

    @field_validator("completed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("delivery receipt timestamp must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_failure(self) -> AdapterDeliveryReceipt:
        if self.status is DeliveryStatus.FAILED and self.error_code is None:
            raise ValueError("failed adapter delivery requires an error code")
        if self.status is not DeliveryStatus.FAILED and self.error_code is not None:
            raise ValueError("non-failed adapter delivery cannot contain an error")
        return self


class AdapterIngressRecord(StrictModel):
    delivery_id: NonEmptyId
    envelope_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    event_id: NonEmptyId
    cycle_id: NonEmptyId
    kernel_duplicate: bool
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ingress record timestamp must include a timezone")
        return value.astimezone(UTC)


class AdapterDispatchRecord(StrictModel):
    command: AdapterOutboundCommand
    decision: AdapterDispatchDecision
    state: DispatchState
    receipt: AdapterDeliveryReceipt | ExternalDeliveryReceipt | None
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("dispatch record timestamps must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_state(self) -> AdapterDispatchRecord:
        if self.updated_at < self.created_at:
            raise ValueError("dispatch record updated_at must not precede created_at")
        if self.decision.command_id != self.command.command_id:
            raise ValueError("dispatch decision must reference its command")
        if self.state is DispatchState.RESERVED and self.receipt is not None:
            raise ValueError("reserved dispatch cannot already have a receipt")
        if self.state is DispatchState.FINALIZED and self.receipt is None:
            raise ValueError("finalized dispatch requires a receipt")
        if self.receipt is not None and (
            self.receipt.command_id != self.command.command_id
            or self.receipt.idempotency_key != self.command.idempotency_key
        ):
            raise ValueError("delivery receipt does not match its command")
        if isinstance(self.receipt, AdapterDeliveryReceipt):
            allowed_statuses = {
                DispatchOutcome.SUPPRESSED_SHADOW: {DeliveryStatus.SUPPRESSED},
                DispatchOutcome.BLOCKED_NOT_CANARY: {DeliveryStatus.BLOCKED},
                DispatchOutcome.BLOCKED_RATE_LIMIT: {DeliveryStatus.BLOCKED},
                DispatchOutcome.BLOCKED_MISSING_CONTENT: {DeliveryStatus.BLOCKED},
                DispatchOutcome.SIMULATE_CANARY: {
                    DeliveryStatus.SIMULATED,
                    DeliveryStatus.FAILED,
                },
                DispatchOutcome.QUEUE_EXTERNAL_CANARY: set(),
            }[self.decision.outcome]
            if self.receipt.status not in allowed_statuses:
                raise ValueError("delivery receipt status is incompatible with dispatch decision")
        if isinstance(self.receipt, ExternalDeliveryReceipt):
            if self.decision.outcome is not DispatchOutcome.QUEUE_EXTERNAL_CANARY:
                raise ValueError("external receipt requires an external-canary dispatch")
            if self.receipt.platform is not self.command.platform:
                raise ValueError("external receipt platform does not match its command")
            if self.receipt.status not in set(ExternalReceiptStatus):
                raise ValueError("unsupported external delivery status")
        return self
