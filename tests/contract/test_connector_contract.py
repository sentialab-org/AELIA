from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from aelia.contracts.connector import (
    CURRENT_EXTERNAL_RECEIPT_SCHEMA_VERSION,
    ExternalDeliveryReceipt,
    ExternalReceiptStatus,
)
from aelia.contracts.events import Platform


def _receipt(**updates: object) -> ExternalDeliveryReceipt:
    values: dict[str, object] = {
        "schema_version": CURRENT_EXTERNAL_RECEIPT_SCHEMA_VERSION,
        "receipt_id": "receipt-001",
        "command_id": "command-001",
        "idempotency_key": "idempotency-001",
        "platform": Platform.DISCORD,
        "connector_id": "connector-001",
        "status": ExternalReceiptStatus.SENT,
        "side_effect_performed": True,
        "platform_message_id": "platform-message-001",
        "completed_at": datetime(2026, 7, 30, tzinfo=UTC),
    }
    values.update(updates)
    return ExternalDeliveryReceipt.model_validate(values)


def test_sent_external_receipt_requires_platform_evidence() -> None:
    receipt = _receipt()

    assert receipt.status is ExternalReceiptStatus.SENT
    assert receipt.side_effect_performed is True
    assert receipt.platform_message_id == "platform-message-001"

    with pytest.raises(ValidationError, match="performed side effect and message id"):
        _receipt(side_effect_performed=False, platform_message_id=None)


def test_not_sent_external_receipt_is_safe_to_classify_for_retry() -> None:
    receipt = _receipt(
        status=ExternalReceiptStatus.NOT_SENT,
        side_effect_performed=False,
        platform_message_id=None,
        error_code="permission_denied",
        retryable=False,
    )

    assert receipt.side_effect_performed is False
    assert receipt.error_code == "permission_denied"


def test_ambiguous_delivery_cannot_claim_retry_safety() -> None:
    receipt = _receipt(
        status=ExternalReceiptStatus.UNKNOWN,
        side_effect_performed=None,
        platform_message_id=None,
        error_code="transport_timeout_after_request",
    )

    assert receipt.status is ExternalReceiptStatus.UNKNOWN
    assert receipt.retryable is False

    with pytest.raises(ValidationError, match="reconciled before retry"):
        _receipt(
            status=ExternalReceiptStatus.UNKNOWN,
            side_effect_performed=None,
            platform_message_id=None,
            error_code="transport_timeout_after_request",
            retryable=True,
        )


def test_external_receipt_rejects_non_external_platform_and_naive_time() -> None:
    with pytest.raises(ValidationError, match="real external platform"):
        _receipt(platform=Platform.TEST)
    with pytest.raises(ValidationError, match="include a timezone"):
        _receipt(completed_at=datetime(2026, 7, 30))
