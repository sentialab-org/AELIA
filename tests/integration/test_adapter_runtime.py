from __future__ import annotations

from pathlib import Path

import pytest

from polyverse.adapters.repository import AdapterConflictError
from polyverse.adapters.runtime import CliKernelAdapter, MockAdapterTransport
from polyverse.contracts.adapter import (
    AdapterDeliveryReceipt,
    AdapterMode,
    AdapterOutboundCommand,
    AdapterPolicyConfig,
    DeliveryStatus,
    DispatchOutcome,
    DispatchState,
)
from polyverse.contracts.connector import (
    CURRENT_EXTERNAL_RECEIPT_SCHEMA_VERSION,
    ExternalDeliveryReceipt,
    ExternalReceiptStatus,
)
from polyverse.contracts.events import ChannelType, Platform
from polyverse.runtime.ports import MockLanguageGenerator
from tests.helpers import (
    make_adapter,
    make_adapter_envelope,
)


async def test_shadow_adapter_suppresses_output_and_is_reconnect_idempotent(
    tmp_path: Path,
) -> None:
    kernel_repository, _, _, adapter, transport = await make_adapter(tmp_path)
    envelope = make_adapter_envelope()

    first = await adapter.ingest(envelope)
    same_delivery = await adapter.ingest(envelope)
    reconnect = await adapter.ingest(
        envelope.model_copy(
            update={
                "delivery_id": "delivery-reconnect",
                "idempotency_key": "ingress:delivery-reconnect",
            }
        )
    )

    assert first.trace.selected_action is not None
    assert first.dispatch is not None
    assert first.dispatch.state is DispatchState.FINALIZED
    assert first.dispatch.decision.outcome is DispatchOutcome.SUPPRESSED_SHADOW
    assert first.dispatch.receipt is not None
    assert first.dispatch.receipt.status is DeliveryStatus.SUPPRESSED
    assert first.dispatch.receipt.side_effect_performed is False
    assert same_delivery.ingress_duplicate is True
    assert reconnect.kernel_duplicate is True
    assert reconnect.dispatch == first.dispatch
    assert transport.calls == []

    async with kernel_repository.database.connection() as connection:
        ingress_cursor = await connection.execute("SELECT count(*) FROM adapter_ingress")
        ingress_count = await ingress_cursor.fetchone()
        dispatch_cursor = await connection.execute("SELECT count(*) FROM adapter_dispatches")
        dispatch_count = await dispatch_cursor.fetchone()
    assert ingress_count is not None and int(ingress_count[0]) == 2
    assert dispatch_count is not None and int(dispatch_count[0]) == 1


async def test_ingress_conflict_is_rejected_before_new_kernel_event(
    tmp_path: Path,
) -> None:
    kernel_repository, _, _, adapter, _ = await make_adapter(tmp_path)
    envelope = make_adapter_envelope()
    await adapter.ingest(envelope)
    conflicting_event = envelope.event.model_copy(update={"content": "different payload"})
    conflicting = envelope.model_copy(update={"event": conflicting_event})

    with pytest.raises(AdapterConflictError, match="different envelope"):
        await adapter.ingest(conflicting)

    async with kernel_repository.database.connection() as connection:
        cursor = await connection.execute("SELECT count(*) FROM inbound_events")
        row = await cursor.fetchone()
    assert row is not None
    assert int(row[0]) == 1


async def test_test_canary_is_allowlisted_rate_limited_and_transport_idempotent(
    tmp_path: Path,
) -> None:
    conversation_id = "adapter-canary-001"
    _, _, _, adapter, transport = await make_adapter(
        tmp_path,
        mode=AdapterMode.TEST_CANARY,
        canary_conversation_ids=(conversation_id,),
        conversation_limit_per_hour=1,
    )
    first_envelope = make_adapter_envelope(
        delivery_id="canary-delivery-1",
        event_id="canary-event-1",
        conversation_id=conversation_id,
    )
    second_envelope = make_adapter_envelope(
        delivery_id="canary-delivery-2",
        event_id="canary-event-2",
        conversation_id=conversation_id,
        channel_type=ChannelType.DM,
    )

    first = await adapter.ingest(first_envelope)
    repeated = await adapter.ingest(first_envelope)
    second = await adapter.ingest(second_envelope)

    assert first.dispatch is not None and first.dispatch.receipt is not None
    assert first.dispatch.decision.outcome is DispatchOutcome.SIMULATE_CANARY
    assert first.dispatch.receipt.status is DeliveryStatus.SIMULATED
    assert first.dispatch.receipt.side_effect_performed is False
    assert repeated.dispatch == first.dispatch
    assert second.dispatch is not None and second.dispatch.receipt is not None
    assert second.dispatch.decision.outcome is DispatchOutcome.BLOCKED_RATE_LIMIT
    assert second.dispatch.receipt.status is DeliveryStatus.BLOCKED
    assert len(transport.calls) == 1


async def test_test_canary_blocks_non_allowlisted_and_missing_content(
    tmp_path: Path,
) -> None:
    allowed = "allowed-conversation"
    _, _, _, adapter, transport = await make_adapter(
        tmp_path / "not-allowed",
        mode=AdapterMode.TEST_CANARY,
        canary_conversation_ids=(allowed,),
    )
    not_allowed = await adapter.ingest(
        make_adapter_envelope(conversation_id="different-conversation")
    )

    _, _, _, contentless_adapter, contentless_transport = await make_adapter(
        tmp_path / "contentless",
        mode=AdapterMode.TEST_CANARY,
        canary_conversation_ids=(allowed,),
        language_generator=MockLanguageGenerator(),
    )
    contentless = await contentless_adapter.ingest(
        make_adapter_envelope(
            delivery_id="contentless-delivery",
            event_id="contentless-event",
            conversation_id=allowed,
        )
    )

    assert not_allowed.dispatch is not None
    assert not_allowed.dispatch.decision.outcome is DispatchOutcome.BLOCKED_NOT_CANARY
    assert contentless.dispatch is not None
    assert contentless.dispatch.decision.outcome is DispatchOutcome.BLOCKED_MISSING_CONTENT
    assert transport.calls == []
    assert contentless_transport.calls == []


async def test_external_canary_queues_until_connector_receipt_and_is_idempotent(
    tmp_path: Path,
) -> None:
    conversation_id = "external-canary"
    _, _, adapter_repository, adapter, transport = await make_adapter(
        tmp_path,
        mode=AdapterMode.EXTERNAL_CANARY,
        canary_conversation_ids=(conversation_id,),
    )
    envelope = make_adapter_envelope(
        delivery_id="external-delivery",
        event_id="external-event",
        conversation_id=conversation_id,
    )
    envelope = envelope.model_copy(
        update={"event": envelope.event.model_copy(update={"platform": Platform.DISCORD_SELFBOT})}
    )

    queued = await adapter.ingest(envelope)

    assert queued.dispatch is not None
    assert queued.dispatch.decision.outcome is DispatchOutcome.QUEUE_EXTERNAL_CANARY
    assert queued.dispatch.state is DispatchState.RESERVED
    assert queued.dispatch.receipt is None
    assert transport.calls == []

    command = queued.dispatch.command
    receipt = ExternalDeliveryReceipt(
        schema_version=CURRENT_EXTERNAL_RECEIPT_SCHEMA_VERSION,
        receipt_id="external-receipt-001",
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        platform=Platform.DISCORD_SELFBOT,
        connector_id="discord-selfbot-v2",
        status=ExternalReceiptStatus.SENT,
        side_effect_performed=True,
        platform_message_id="discord-message-001",
        completed_at=command.created_at,
    )

    finalized = await adapter_repository.finalize_external_dispatch(receipt)
    repeated = await adapter_repository.finalize_external_dispatch(receipt)

    assert finalized.state is DispatchState.FINALIZED
    assert finalized.receipt == receipt
    assert repeated == finalized


class SimulatedProcessCrash(BaseException):
    pass


class CrashBeforeTransport:
    async def dispatch(
        self,
        command: AdapterOutboundCommand,
    ) -> AdapterDeliveryReceipt:
        raise SimulatedProcessCrash


async def test_pending_outbox_recovers_after_crash_without_duplicate_transport(
    tmp_path: Path,
) -> None:
    conversation_id = "recovery-canary"
    (
        kernel_repository,
        orchestrator,
        adapter_repository,
        _,
        _,
    ) = await make_adapter(
        tmp_path,
        mode=AdapterMode.TEST_CANARY,
        canary_conversation_ids=(conversation_id,),
    )
    crashing_adapter = CliKernelAdapter(
        processor=orchestrator,
        kernel_repository=kernel_repository,
        adapter_repository=adapter_repository,
        config=AdapterPolicyConfig(
            policy_version="adapter-recovery-test-v1",
            mode=AdapterMode.TEST_CANARY,
            canary_conversation_ids=(conversation_id,),
            conversation_limit_per_hour=5,
        ),
        transport=CrashBeforeTransport(),
    )
    envelope = make_adapter_envelope(
        delivery_id="recovery-delivery",
        event_id="recovery-event",
        conversation_id=conversation_id,
    )

    with pytest.raises(SimulatedProcessCrash):
        await crashing_adapter.ingest(envelope)

    pending = await adapter_repository.list_pending_dispatches()
    assert len(pending) == 1
    assert pending[0].state is DispatchState.RESERVED

    recovery_transport = MockAdapterTransport()
    recovery_adapter = CliKernelAdapter(
        processor=orchestrator,
        kernel_repository=kernel_repository,
        adapter_repository=adapter_repository,
        config=crashing_adapter.config,
        transport=recovery_transport,
    )
    recovered = await recovery_adapter.recover_pending()
    recovered_again = await recovery_adapter.recover_pending()
    reconnect = await recovery_adapter.ingest(envelope)

    assert len(recovered) == 1
    assert recovered[0].state is DispatchState.FINALIZED
    assert recovered[0].receipt is not None
    assert recovered[0].receipt.status is DeliveryStatus.SIMULATED
    assert recovered_again == ()
    assert reconnect.dispatch == recovered[0]
    assert recovery_transport.calls == [recovered[0].command.idempotency_key]


async def test_kernel_commit_before_ingress_record_is_recoverable(
    tmp_path: Path,
) -> None:
    _, orchestrator, adapter_repository, adapter, _ = await make_adapter(tmp_path)
    envelope = make_adapter_envelope(
        delivery_id="post-kernel-crash-delivery",
        event_id="post-kernel-crash-event",
    )
    committed = await orchestrator.process(envelope.event)
    assert await adapter_repository.get_ingress(envelope.delivery_id) is None

    recovered = await adapter.ingest(envelope)

    assert recovered.kernel_duplicate is True
    assert recovered.trace == committed.trace
    assert recovered.ingress.event_id == envelope.event.event_id
