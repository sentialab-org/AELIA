from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Final

from polyverse.adapters.runtime import AdapterProcessResult, RuntimeAdapter
from polyverse.app.bootstrap import (
    RuntimeComposition,
    build_adapter_policy,
    build_composition,
    initialize_composition,
)
from polyverse.app.config import GateSettings, Settings, load_settings
from polyverse.contracts.adapter import AdapterDispatchRecord, AdapterInboundEnvelope
from polyverse.contracts.connector import ExternalDeliveryReceipt


class RuntimeProtocolError(RuntimeError):
    """A request crossed the protocol boundary with an invalid gate or receipt."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GateResolution:
    name: str
    config: GateSettings


class RuntimeApplication:
    """Long-lived platform-neutral runtime service.

    The application owns the orchestrator, repositories, LLM client, and
    adapter outbox for the entire backend process. Platform gates only submit
    versioned envelopes and receipts through this object's API boundary.
    """

    API_VERSION: Final[str] = "1.0.0"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        composition: RuntimeComposition | None = None,
    ) -> None:
        self.composition = composition or build_composition(settings or load_settings())
        self.settings = self.composition.settings
        self.ready = False
        self.startup_error: str | None = None
        # The backend owns one resident persona. Serialize the complete ingress
        # lifecycle so every gate observes a single persona-state timeline.
        # This is process-local: run one backend worker per SQLite database.
        self._persona_ingress_lock = asyncio.Lock()

    async def initialize(self) -> None:
        try:
            await initialize_composition(self.composition)
            self.ready = True
            self.startup_error = None
        except Exception as exc:
            self.ready = False
            self.startup_error = type(exc).__name__
            raise

    async def shutdown(self) -> None:
        # Database connections are scoped per operation; this method is kept as
        # an explicit lifecycle hook for future pooled resources.
        self.ready = False

    def resolve_gate(self, adapter_id: str) -> GateResolution:
        for name, gate in self.settings.platforms.items():
            if gate.adapter_id == adapter_id:
                if not gate.enabled:
                    raise RuntimeProtocolError("gate_disabled", f"gate {adapter_id!r} is disabled")
                return GateResolution(name=name, config=gate)
        raise RuntimeProtocolError("unknown_gate", f"no configured gate for adapter {adapter_id!r}")

    def _validate_envelope_gate(self, envelope: AdapterInboundEnvelope) -> GateResolution:
        resolution = self.resolve_gate(envelope.adapter_id)
        gate = resolution.config
        if envelope.event.platform is not gate.platform:
            raise RuntimeProtocolError(
                "platform_mismatch",
                "gate "
                f"{gate.adapter_id!r} does not accept platform "
                f"{envelope.event.platform.value!r}",
            )
        if gate.allowed_actor_ids and envelope.event.actor_id not in gate.allowed_actor_ids:
            raise RuntimeProtocolError("actor_not_allowed", "inbound actor is not allowlisted")
        if gate.allowed_conversation_ids != ("-1",) and (
            envelope.event.conversation_id not in gate.allowed_conversation_ids
        ):
            raise RuntimeProtocolError(
                "conversation_not_allowed",
                "inbound conversation is not allowlisted by the backend gate policy",
            )
        return resolution

    async def ingest(self, envelope: AdapterInboundEnvelope) -> AdapterProcessResult:
        if not self.ready:
            raise RuntimeProtocolError("backend_not_ready", "runtime backend is not ready")
        resolution = self._validate_envelope_gate(envelope)
        async with self._persona_ingress_lock:
            adapter = RuntimeAdapter(
                processor=self.composition.processor,
                kernel_repository=self.composition.repository,
                adapter_repository=self.composition.adapter_repository,
                config=build_adapter_policy(
                    resolution.config,
                    conversation_id=envelope.event.conversation_id,
                ),
            )
            return await adapter.ingest(envelope)

    async def record_external_receipt(
        self,
        receipt: ExternalDeliveryReceipt,
    ) -> AdapterDispatchRecord:
        if not self.ready:
            raise RuntimeProtocolError("backend_not_ready", "runtime backend is not ready")
        resolution = self.resolve_gate(receipt.connector_id)
        if resolution.config.platform is not receipt.platform:
            raise RuntimeProtocolError(
                "platform_mismatch",
                "receipt platform does not match the configured gate",
            )
        try:
            return await self.composition.adapter_repository.finalize_external_dispatch(receipt)
        except Exception as exc:
            # Preserve repository conflict semantics while giving HTTP callers
            # a stable protocol error class/code.
            raise RuntimeProtocolError("receipt_rejected", str(exc)) from exc

    def status_payload(self) -> dict[str, object]:
        return {
            "api_version": self.API_VERSION,
            "service": "polyverse-runtime-backend",
            "ready": self.ready,
            "environment": self.settings.environment.value,
            "agent_actor_id": self.settings.agent_actor_id,
            "configured_gates": tuple(
                gate.adapter_id for gate in self.settings.platforms.values() if gate.enabled
            ),
            "llm_provider": self.settings.llm_provider.value,
            "llm_model": self.settings.llm_model,
            "database_path": str(self.settings.database_path),
        }


__all__ = ["GateResolution", "RuntimeApplication", "RuntimeProtocolError"]
