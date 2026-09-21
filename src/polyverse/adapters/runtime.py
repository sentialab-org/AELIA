from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from polyverse.adapters.repository import (
    AdapterConcurrentStateError,
    SqliteAdapterRepository,
)
from polyverse.contracts.adapter import (
    CURRENT_ADAPTER_OUTBOUND_SCHEMA_VERSION,
    CURRENT_ADAPTER_RECEIPT_SCHEMA_VERSION,
    AdapterDeliveryReceipt,
    AdapterDispatchDecision,
    AdapterDispatchRecord,
    AdapterInboundEnvelope,
    AdapterIngressRecord,
    AdapterMode,
    AdapterOutboundCommand,
    AdapterPolicyConfig,
    DeliveryStatus,
    DispatchOutcome,
)
from polyverse.contracts.events import InboundEvent
from polyverse.contracts.traces import CycleTrace
from polyverse.runtime.orchestrator import ProcessResult
from polyverse.storage.repositories import KernelRepository

ADAPTER_ROUTING_POLICY_VERSION = "adapter-routing-v1"


class KernelProcessor(Protocol):
    async def process(self, event: InboundEvent) -> ProcessResult: ...


class AdapterTransportPort(Protocol):
    async def dispatch(
        self,
        command: AdapterOutboundCommand,
    ) -> AdapterDeliveryReceipt: ...


class MockAdapterTransport:
    """Idempotent test transport; it never performs an external side effect."""

    def __init__(self) -> None:
        self.receipts_by_key: dict[str, AdapterDeliveryReceipt] = {}
        self.calls: list[str] = []

    async def dispatch(
        self,
        command: AdapterOutboundCommand,
    ) -> AdapterDeliveryReceipt:
        existing = self.receipts_by_key.get(command.idempotency_key)
        if existing is not None:
            return existing
        receipt = AdapterDeliveryReceipt(
            schema_version=CURRENT_ADAPTER_RECEIPT_SCHEMA_VERSION,
            receipt_id=self._receipt_id(command.command_id, "simulated"),
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            status=DeliveryStatus.SIMULATED,
            transport="mock-adapter-transport-v1",
            side_effect_performed=False,
            completed_at=command.created_at,
        )
        self.receipts_by_key[command.idempotency_key] = receipt
        self.calls.append(command.idempotency_key)
        return receipt

    @staticmethod
    def _receipt_id(command_id: str, status: str) -> str:
        digest = hashlib.sha256(f"{command_id}\x1f{status}".encode()).hexdigest()[:24]
        return f"adapter-receipt:{digest}"


@dataclass(frozen=True)
class AdapterProcessResult:
    trace: CycleTrace
    ingress: AdapterIngressRecord
    dispatch: AdapterDispatchRecord | None
    kernel_duplicate: bool
    ingress_duplicate: bool


class AdapterRoutingPolicy:
    def decide(
        self,
        *,
        command: AdapterOutboundCommand,
        config: AdapterPolicyConfig,
        recent_conversation_dispatches: int,
    ) -> AdapterDispatchDecision:
        reasons: tuple[str, ...]
        if config.mode is AdapterMode.SHADOW:
            outcome = DispatchOutcome.SUPPRESSED_SHADOW
            reasons = ("adapter_shadow_mode", "no_transport_call")
        elif command.target_conversation_id not in config.canary_conversation_ids:
            outcome = DispatchOutcome.BLOCKED_NOT_CANARY
            reasons = ("conversation_not_in_test_canary",)
        elif command.content is None or not command.content.strip():
            outcome = DispatchOutcome.BLOCKED_MISSING_CONTENT
            reasons = ("language_generation_has_no_deliverable_content",)
        elif recent_conversation_dispatches >= config.conversation_limit_per_hour:
            outcome = DispatchOutcome.BLOCKED_RATE_LIMIT
            reasons = ("adapter_conversation_rate_limited",)
        elif config.mode is AdapterMode.TEST_CANARY:
            outcome = DispatchOutcome.SIMULATE_CANARY
            reasons = (
                "test_canary_conversation_allowed",
                "mock_transport_only",
            )
        else:
            outcome = DispatchOutcome.QUEUE_EXTERNAL_CANARY
            reasons = (
                "external_canary_conversation_allowed",
                "external_connector_receipt_required",
            )
        return AdapterDispatchDecision(
            policy_version=ADAPTER_ROUTING_POLICY_VERSION,
            command_id=command.command_id,
            mode=config.mode,
            outcome=outcome,
            recent_conversation_dispatches=recent_conversation_dispatches,
            conversation_limit_per_hour=config.conversation_limit_per_hour,
            reason_codes=reasons,
            decided_at=command.created_at,
        )


class RuntimeAdapter:
    """Platform-neutral adapter service with reconnect-safe ingress and an outbox."""

    def __init__(
        self,
        *,
        processor: KernelProcessor,
        kernel_repository: KernelRepository,
        adapter_repository: SqliteAdapterRepository,
        config: AdapterPolicyConfig,
        transport: AdapterTransportPort | None = None,
        reservation_retries: int = 3,
    ) -> None:
        if reservation_retries < 1:
            raise ValueError("reservation_retries must be positive")
        self.processor = processor
        self.kernel_repository = kernel_repository
        self.adapter_repository = adapter_repository
        self.config = config
        self.transport = transport or MockAdapterTransport()
        self.reservation_retries = reservation_retries

    async def initialize(self) -> None:
        await self.adapter_repository.initialize()

    async def ingest(
        self,
        envelope: AdapterInboundEnvelope,
    ) -> AdapterProcessResult:
        existing_ingress = await self.adapter_repository.preflight_ingress(envelope)
        if existing_ingress is not None:
            trace = await self.kernel_repository.get_cycle(existing_ingress.cycle_id)
            dispatch = await self._dispatch_trace(envelope, trace)
            return AdapterProcessResult(
                trace=trace,
                ingress=existing_ingress,
                dispatch=dispatch,
                kernel_duplicate=existing_ingress.kernel_duplicate,
                ingress_duplicate=True,
            )

        processed = await self.processor.process(envelope.event)
        ingress, created = await self.adapter_repository.record_ingress(
            envelope=envelope,
            cycle_id=processed.trace.cycle_id,
            kernel_duplicate=processed.duplicate,
        )
        dispatch = await self._dispatch_trace(envelope, processed.trace)
        return AdapterProcessResult(
            trace=processed.trace,
            ingress=ingress,
            dispatch=dispatch,
            kernel_duplicate=processed.duplicate,
            ingress_duplicate=not created,
        )

    async def recover_pending(
        self,
        *,
        limit: int = 100,
    ) -> tuple[AdapterDispatchRecord, ...]:
        pending = await self.adapter_repository.list_pending_dispatches(limit=limit)
        recovered = []
        for record in pending:
            recovered.append(await self._complete_reservation(record))
        return tuple(recovered)

    async def _dispatch_trace(
        self,
        envelope: AdapterInboundEnvelope,
        trace: CycleTrace,
    ) -> AdapterDispatchRecord | None:
        action = trace.selected_action
        if action is None:
            return None
        existing = await self.adapter_repository.get_dispatch_for_action(action.action_id)
        if existing is not None:
            if existing.receipt is not None:
                return existing
            return await self._complete_reservation(existing)

        command = AdapterOutboundCommand(
            schema_version=CURRENT_ADAPTER_OUTBOUND_SCHEMA_VERSION,
            command_id=f"adapter-command:{action.action_id}",
            action_id=action.action_id,
            cycle_id=action.cycle_id,
            platform=envelope.event.platform,
            action_type=action.action_type,
            target_conversation_id=action.target.conversation_id,
            reply_to_event_id=action.target.reply_to_event_id,
            content=(
                trace.language_generation.content if trace.language_generation is not None else None
            ),
            constraints=action.content_plan.constraints,
            risk_class=action.risk_class,
            idempotency_key=action.idempotency_key,
            created_at=action.created_at,
        )
        for _ in range(self.reservation_retries):
            recent_count = await self.adapter_repository.recent_canary_dispatch_count(
                conversation_id=command.target_conversation_id,
                window_start=command.created_at - timedelta(hours=1),
            )
            decision = AdapterRoutingPolicy().decide(
                command=command,
                config=self.config,
                recent_conversation_dispatches=recent_count,
            )
            try:
                reservation = await self.adapter_repository.reserve_dispatch(
                    command=command,
                    decision=decision,
                )
            except AdapterConcurrentStateError:
                continue
            if reservation.record.receipt is not None:
                return reservation.record
            return await self._complete_reservation(reservation.record)
        raise AdapterConcurrentStateError(
            "adapter dispatch reservation exhausted rate-state retries"
        )

    async def _complete_reservation(
        self,
        record: AdapterDispatchRecord,
    ) -> AdapterDispatchRecord:
        if record.receipt is not None:
            return record
        if record.decision.outcome is DispatchOutcome.QUEUE_EXTERNAL_CANARY:
            return record
        if record.decision.outcome is DispatchOutcome.SIMULATE_CANARY:
            try:
                receipt = await self.transport.dispatch(record.command)
            except Exception as exc:
                receipt = AdapterDeliveryReceipt(
                    schema_version=CURRENT_ADAPTER_RECEIPT_SCHEMA_VERSION,
                    receipt_id=MockAdapterTransport._receipt_id(
                        record.command.command_id,
                        "failed",
                    ),
                    command_id=record.command.command_id,
                    idempotency_key=record.command.idempotency_key,
                    status=DeliveryStatus.FAILED,
                    transport=type(self.transport).__name__,
                    side_effect_performed=False,
                    error_code=type(exc).__name__,
                    retryable=True,
                    completed_at=record.decision.decided_at,
                )
        else:
            status = (
                DeliveryStatus.SUPPRESSED
                if record.decision.outcome is DispatchOutcome.SUPPRESSED_SHADOW
                else DeliveryStatus.BLOCKED
            )
            receipt = AdapterDeliveryReceipt(
                schema_version=CURRENT_ADAPTER_RECEIPT_SCHEMA_VERSION,
                receipt_id=MockAdapterTransport._receipt_id(
                    record.command.command_id,
                    status.value,
                ),
                command_id=record.command.command_id,
                idempotency_key=record.command.idempotency_key,
                status=status,
                transport="adapter-routing-policy",
                side_effect_performed=False,
                completed_at=record.decision.decided_at,
            )
        return await self.adapter_repository.finalize_dispatch(receipt)


# Compatibility name for the frozen CLI command and existing V2 callers. The
# implementation is now owned by the independent runtime backend rather than
# by a per-message CLI subprocess.
CliKernelAdapter = RuntimeAdapter


__all__ = [
    "ADAPTER_ROUTING_POLICY_VERSION",
    "AdapterProcessResult",
    "AdapterRoutingPolicy",
    "AdapterTransportPort",
    "CliKernelAdapter",
    "KernelProcessor",
    "MockAdapterTransport",
    "RuntimeAdapter",
]
