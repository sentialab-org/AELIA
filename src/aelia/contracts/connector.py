from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from aelia.contracts.common import NonEmptyId, StrictModel
from aelia.contracts.events import Platform

ConnectorCapabilitySchemaVersion = Literal["1.0.0"]
ExternalReceiptSchemaVersion = Literal["2.0.0"]
CURRENT_CONNECTOR_CAPABILITY_SCHEMA_VERSION: ConnectorCapabilitySchemaVersion = "1.0.0"
CURRENT_EXTERNAL_RECEIPT_SCHEMA_VERSION: ExternalReceiptSchemaVersion = "2.0.0"


class ExternalReceiptStatus(StrEnum):
    SENT = "sent"
    NOT_SENT = "not_sent"
    UNKNOWN = "unknown"


class ExternalDeliveryReceipt(StrictModel):
    """Receipt from an external platform gate finalizing a reserved dispatch."""

    schema_version: ExternalReceiptSchemaVersion
    receipt_id: NonEmptyId
    command_id: NonEmptyId
    idempotency_key: NonEmptyId
    platform: Platform
    connector_id: NonEmptyId
    status: ExternalReceiptStatus
    side_effect_performed: bool | None
    platform_message_id: NonEmptyId | None = None
    error_code: Annotated[str | None, Field(max_length=128)] = None
    retryable: bool = False
    completed_at: datetime

    @field_validator("completed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("external receipt timestamp must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_delivery_semantics(self) -> ExternalDeliveryReceipt:
        if self.platform in {Platform.CLI, Platform.TEST}:
            raise ValueError("external receipt requires a real external platform")
        if self.status is ExternalReceiptStatus.SENT:
            if self.side_effect_performed is not True or self.platform_message_id is None:
                raise ValueError("sent receipt requires a performed side effect and message id")
            if self.error_code is not None or self.retryable:
                raise ValueError("sent receipt cannot contain an error or be retryable")
        elif self.status is ExternalReceiptStatus.NOT_SENT:
            if self.side_effect_performed is not False or self.error_code is None:
                raise ValueError("not-sent receipt requires no side effect and an error code")
            if self.platform_message_id is not None:
                raise ValueError("not-sent receipt cannot contain a platform message id")
        else:
            if self.side_effect_performed is not None or self.error_code is None:
                raise ValueError("unknown receipt requires ambiguous side effect and an error code")
            if self.retryable:
                raise ValueError("unknown delivery must be reconciled before retry")
        return self


class ConnectorCapabilities(StrictModel):
    schema_version: ConnectorCapabilitySchemaVersion
    connector_id: NonEmptyId
    connector_version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    platform: Platform
    account_model: Annotated[str, Field(min_length=1, max_length=128)]
    inbound_schema_version: Literal["1.0.0"]
    outbound_schema_version: Literal["1.1.0"]
    receipt_schema_version: Literal["2.0.0"]
    supports_idempotency_lookup: bool
    supports_canary_allowlist: bool
    supports_kill_switch: bool
    supports_reconnect_cursor: bool
    supports_permission_probe: bool
    supports_rate_limit_observation: bool
    redacts_secrets: bool

    @model_validator(mode="after")
    def require_external_platform(self) -> ConnectorCapabilities:
        if self.platform in {Platform.CLI, Platform.TEST}:
            raise ValueError("connector capability manifest requires an external platform")
        return self


class ConnectorReadinessCheck(StrictModel):
    code: Annotated[str, Field(min_length=1, max_length=128)]
    passed: bool
    evidence: Annotated[str, Field(min_length=1, max_length=512)]


class ConnectorReadinessReport(StrictModel):
    policy_version: Literal["connector-readiness-v1"]
    connector_id: NonEmptyId
    platform: Platform
    ready_for_authorized_canary: bool
    checks: Annotated[tuple[ConnectorReadinessCheck, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_outcome(self) -> ConnectorReadinessReport:
        if self.ready_for_authorized_canary != all(check.passed for check in self.checks):
            raise ValueError("connector readiness outcome must equal all checks")
        return self
