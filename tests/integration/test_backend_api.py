from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from polyverse.app.config import GateSettings, LlmProvider, Settings
from polyverse.backend.api import create_app
from polyverse.backend.application import RuntimeApplication
from polyverse.contracts.actions import LanguageGenerationResult, OutboundAction
from polyverse.contracts.adapter import AdapterInboundEnvelope, AdapterMode
from polyverse.contracts.connector import (
    CURRENT_EXTERNAL_RECEIPT_SCHEMA_VERSION,
    ExternalDeliveryReceipt,
    ExternalReceiptStatus,
)
from polyverse.contracts.events import InboundEvent, Platform
from polyverse.persona.models import PersonaView
from polyverse.storage.repositories import ConcurrentStateError
from tests.helpers import FixtureTextLanguageGenerator, make_adapter_envelope

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def runtime_settings(
    tmp_path: Path,
    *,
    gate_token: str | None = None,
    gate_mode: AdapterMode = AdapterMode.TEST_CANARY,
    send_enabled: bool = False,
) -> Settings:
    settings = Settings(
        _env_file=None,
        llm_provider=LlmProvider.MOCK,
        database_path=tmp_path / "backend.db",
        persona_manifest_path=PROJECT_ROOT / "src/polyverse/persona/source/manifest.json",
        agent_actor_id="agent-001",
        platforms={
            "discord_selfbot": GateSettings(
                enabled=True,
                adapter_id="discord-selfbot-v2",
                platform=Platform.DISCORD_SELFBOT,
                mode=gate_mode,
                allowed_conversation_ids=("-1",),
                send_enabled=send_enabled,
            )
        },
    )
    if gate_token is not None:
        settings._runtime_gate_token = SecretStr(gate_token)
    return settings


def discord_envelope(
    *,
    delivery_id: str = "backend-delivery-001",
    event_id: str = "backend-event-001",
    conversation_id: str = "arbitrary-channel-42",
) -> AdapterInboundEnvelope:
    envelope = make_adapter_envelope(
        delivery_id=delivery_id,
        event_id=event_id,
        conversation_id=conversation_id,
    )
    event = envelope.event.model_copy(
        update={
            "platform": Platform.DISCORD_SELFBOT,
            "source_reference": envelope.event.source_reference.model_copy(
                update={"adapter": "discord-selfbot-v2"}
            ),
        }
    )
    return envelope.model_copy(
        update={
            "adapter_id": "discord-selfbot-v2",
            "event": event,
        }
    )


@pytest.mark.asyncio
async def test_live_asgi_backend_accepts_wildcard_gate_and_is_idempotent(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    runtime = RuntimeApplication(settings)
    runtime.composition.processor.language_generator = FixtureTextLanguageGenerator()
    await runtime.initialize()
    app = create_app(settings, runtime=runtime)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://runtime.test",
    ) as client:
        first = await client.post(
            "/v1/gates/ingress",
            json=discord_envelope().model_dump(mode="json"),
        )
        repeated = await client.post(
            "/v1/gates/ingress",
            json=discord_envelope().model_dump(mode="json"),
        )

    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["dispatch"]["decision"]["outcome"] == "simulate_canary"
    assert first_payload["dispatch"]["receipt"]["status"] == "simulated"
    assert repeated.status_code == 200
    assert repeated.json()["ingress_duplicate"] is True
    assert repeated.json()["trace"]["cycle_id"] == first_payload["trace"]["cycle_id"]
    await runtime.shutdown()


class BlockingLanguageGenerator(FixtureTextLanguageGenerator):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(
        self,
        action: OutboundAction,
        *,
        event: InboundEvent,
        persona_view: PersonaView,
    ) -> LanguageGenerationResult:
        self.started.set()
        await self.release.wait()
        return await super().generate(action, event=event, persona_view=persona_view)


@pytest.mark.asyncio
async def test_live_asgi_backend_serializes_concurrent_persona_ingress(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    runtime = RuntimeApplication(settings)
    generator = BlockingLanguageGenerator()
    runtime.composition.processor.language_generator = generator
    await runtime.initialize()
    app = create_app(settings, runtime=runtime)
    first_envelope = discord_envelope(
        delivery_id="backend-delivery-concurrent-1",
        event_id="backend-event-concurrent-1",
        conversation_id="concurrent-channel-1",
    )
    second_envelope = discord_envelope(
        delivery_id="backend-delivery-concurrent-2",
        event_id="backend-event-concurrent-2",
        conversation_id="concurrent-channel-2",
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://runtime.test",
    ) as client:
        first_request = asyncio.create_task(
            client.post("/v1/gates/ingress", json=first_envelope.model_dump(mode="json"))
        )
        await generator.started.wait()
        second_request = asyncio.create_task(
            client.post("/v1/gates/ingress", json=second_envelope.model_dump(mode="json"))
        )
        await asyncio.sleep(0)
        assert not second_request.done()
        generator.release.set()
        first, second = await asyncio.gather(first_request, second_request)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["trace"]["event_id"] == first_envelope.event.event_id
    assert second.json()["trace"]["event_id"] == second_envelope.event.event_id
    assert first.json()["trace"]["internal_transition"]["after"]["version"] == 1
    assert second.json()["trace"]["internal_transition"]["after"]["version"] == 2
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_runtime_returns_json_for_concurrent_state_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = runtime_settings(tmp_path)
    runtime = RuntimeApplication(settings)
    await runtime.initialize()
    app = create_app(settings, runtime=runtime)

    async def raise_conflict(_: AdapterInboundEnvelope) -> object:
        raise ConcurrentStateError("simulated stale persona state")

    monkeypatch.setattr(runtime, "ingest", raise_conflict)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://runtime.test",
    ) as client:
        response = await client.post(
            "/v1/gates/ingress",
            json=discord_envelope().model_dump(mode="json"),
            headers={"x-request-id": "concurrent-conflict-001"},
        )

    assert response.status_code == 409
    assert response.json() == {
        "api_version": "1.0.0",
        "error": "concurrent_state_conflict",
        "message": "persona state changed before the ingress cycle could be committed",
        "request_id": "concurrent-conflict-001",
    }
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_runtime_gate_token_is_enforced(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path, gate_token="runtime-secret")
    runtime = RuntimeApplication(settings)
    await runtime.initialize()
    app = create_app(settings, runtime=runtime)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://runtime.test",
    ) as client:
        denied = await client.get("/runtime/status")
        allowed = await client.get(
            "/runtime/status",
            headers={"Authorization": "Bearer runtime-secret"},
        )

    assert denied.status_code == 401
    assert denied.json()["error"] == "unauthorized"
    assert allowed.status_code == 200
    assert allowed.json()["configured_gates"] == ["discord-selfbot-v2"]
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_runtime_rejects_chunked_body_over_actual_size_limit(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path).model_copy(update={"runtime_max_request_bytes": 1_024})
    runtime = RuntimeApplication(settings)
    await runtime.initialize()
    app = create_app(settings, runtime=runtime)

    async def oversized_body() -> AsyncIterator[bytes]:
        yield b"{" + b'"padding":"' + (b"x" * 1_100) + b'"}'

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://runtime.test",
    ) as client:
        response = await client.post(
            "/v1/gates/ingress",
            content=oversized_body(),
            headers={"content-type": "application/json", "x-request-id": "oversized-001"},
        )

    assert response.status_code == 413
    assert response.json()["error"] == "request_too_large"
    assert response.json()["request_id"] == "oversized-001"
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_external_receipt_endpoint_finalizes_idempotently(tmp_path: Path) -> None:
    settings = runtime_settings(
        tmp_path,
        gate_mode=AdapterMode.EXTERNAL_CANARY,
        send_enabled=True,
    )
    runtime = RuntimeApplication(settings)
    runtime.composition.processor.language_generator = FixtureTextLanguageGenerator()
    await runtime.initialize()
    app = create_app(settings, runtime=runtime)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://runtime.test",
    ) as client:
        ingress = await client.post(
            "/v1/gates/ingress",
            json=discord_envelope().model_dump(mode="json"),
        )
        command = ingress.json()["dispatch"]["command"]
        receipt = ExternalDeliveryReceipt(
            schema_version=CURRENT_EXTERNAL_RECEIPT_SCHEMA_VERSION,
            receipt_id="backend-receipt-001",
            command_id=command["command_id"],
            idempotency_key=command["idempotency_key"],
            platform=Platform.DISCORD_SELFBOT,
            connector_id="discord-selfbot-v2",
            status=ExternalReceiptStatus.SENT,
            side_effect_performed=True,
            platform_message_id="discord-message-001",
            completed_at=datetime.now(UTC),
        )
        first = await client.post(
            "/v1/gates/receipts",
            json=receipt.model_dump(mode="json"),
        )
        repeated = await client.post(
            "/v1/gates/receipts",
            json=receipt.model_dump(mode="json"),
        )

    assert ingress.status_code == 200
    assert ingress.json()["dispatch"]["decision"]["outcome"] == "queue_external_canary"
    assert first.status_code == 200
    assert first.json()["dispatch"]["state"] == "finalized"
    assert repeated.status_code == 200
    assert repeated.json()["dispatch"] == first.json()["dispatch"]
    await runtime.shutdown()
