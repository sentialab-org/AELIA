from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from aelia.cli import _build_parser, _run
from aelia.contracts.adapter import AdapterMode
from aelia.contracts.connector import (
    CURRENT_EXTERNAL_RECEIPT_SCHEMA_VERSION,
    ExternalDeliveryReceipt,
    ExternalReceiptStatus,
)
from aelia.contracts.events import Platform
from tests.helpers import make_adapter, make_adapter_envelope

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_FIXTURE = PROJECT_ROOT / "tests/fixtures/adapter/inbound_envelope.json"
CONNECTOR_CAPABILITY_FIXTURE = PROJECT_ROOT / "tests/fixtures/adapter/connector_capabilities.json"


async def test_cli_fixed_content_canary_is_explicit_and_side_effect_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(PROJECT_ROOT)
    monkeypatch.setenv("AELIA_DATABASE_PATH", str(tmp_path / "canary.db"))
    monkeypatch.setenv("AELIA_AGENT_ACTOR_ID", "agent-001")
    monkeypatch.setenv("AELIA_ADAPTER_MODE", "test_canary")
    monkeypatch.setenv(
        "AELIA_ADAPTER_CANARY_CONVERSATION_IDS",
        '["fixture-adapter-conversation-001"]',
    )
    args = _build_parser().parse_args(
        [
            "adapter",
            "ingest",
            str(ADAPTER_FIXTURE),
            "--test-content",
            "Test-only adapter response.",
        ]
    )

    exit_code = await _run(args)
    captured = capsys.readouterr()
    payload: dict[str, Any] = json.loads(captured.out)
    structured_log: dict[str, Any] = json.loads(captured.err)

    assert exit_code == 0
    assert payload["dispatch"]["decision"]["outcome"] == "simulate_canary"
    assert payload["dispatch"]["receipt"]["status"] == "simulated"
    assert payload["dispatch"]["receipt"]["side_effect_performed"] is False
    assert payload["dispatch"]["command"]["content"] == "Test-only adapter response."
    assert structured_log["event"] == "adapter_ingress_processed"
    assert structured_log["cycle_id"] == payload["trace"]["cycle_id"]
    assert "Test-only adapter response." not in captured.err


async def test_cli_rejects_test_content_in_shadow_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(PROJECT_ROOT)
    monkeypatch.setenv("AELIA_DATABASE_PATH", str(tmp_path / "shadow.db"))
    monkeypatch.setenv("AELIA_ADAPTER_MODE", "shadow")
    args = _build_parser().parse_args(
        [
            "adapter",
            "ingest",
            str(ADAPTER_FIXTURE),
            "--test-content",
            "must not be accepted",
        ]
    )

    with pytest.raises(ValueError, match="requires AELIA_ADAPTER_MODE=test_canary"):
        await _run(args)


async def test_cli_connector_preflight_is_operable_without_a_database(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(PROJECT_ROOT)
    args = _build_parser().parse_args(
        [
            "adapter",
            "connector-preflight",
            str(CONNECTOR_CAPABILITY_FIXTURE),
        ]
    )

    exit_code = await _run(args)
    report: dict[str, Any] = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["connector_id"] == "example-discord-connector"
    assert report["ready_for_authorized_canary"] is True
    assert all(check["passed"] for check in report["checks"])


async def test_cli_records_external_connector_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conversation_id = "cli-external-canary"
    database_directory = tmp_path / "adapter"
    _, _, _, adapter, _ = await make_adapter(
        database_directory,
        mode=AdapterMode.EXTERNAL_CANARY,
        canary_conversation_ids=(conversation_id,),
    )
    envelope = make_adapter_envelope(
        delivery_id="cli-external-delivery",
        event_id="cli-external-event",
        conversation_id=conversation_id,
    )
    envelope = envelope.model_copy(
        update={"event": envelope.event.model_copy(update={"platform": Platform.DISCORD_SELFBOT})}
    )
    queued = await adapter.ingest(envelope)
    assert queued.dispatch is not None
    command = queued.dispatch.command
    receipt = ExternalDeliveryReceipt(
        schema_version=CURRENT_EXTERNAL_RECEIPT_SCHEMA_VERSION,
        receipt_id="cli-external-receipt",
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        platform=Platform.DISCORD_SELFBOT,
        connector_id="discord-selfbot-v2",
        status=ExternalReceiptStatus.SENT,
        side_effect_performed=True,
        platform_message_id="discord-message-1",
        completed_at=datetime.now(UTC),
    )
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(receipt.model_dump_json(), encoding="utf-8")

    monkeypatch.chdir(PROJECT_ROOT)
    monkeypatch.setenv(
        "AELIA_DATABASE_PATH",
        str(database_directory / "aelia-adapter-test.db"),
    )
    args = _build_parser().parse_args(["adapter", "external-receipt", str(receipt_path)])

    exit_code = await _run(args)
    captured = capsys.readouterr()
    payload: dict[str, Any] = json.loads(captured.out)

    assert exit_code == 0
    assert payload["state"] == "finalized"
    assert payload["receipt"]["status"] == "sent"
    assert payload["receipt"]["side_effect_performed"] is True


async def test_cli_llm_doctor_redacts_the_api_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(PROJECT_ROOT)
    monkeypatch.setenv("AELIA_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AELIA_LLM_API_BASE", "https://provider.example.test/v1")
    monkeypatch.setenv("AELIA_LLM_API_KEY", "doctor-test-secret")
    monkeypatch.setenv("AELIA_LLM_MODEL", "test-model")
    args = _build_parser().parse_args(["llm", "doctor"])

    exit_code = await _run(args)
    raw_output = capsys.readouterr().out
    report: dict[str, Any] = json.loads(raw_output)

    assert exit_code == 0
    assert report["configured"] is True
    assert report["config"]["api_key_configured"] is True
    assert report["config"]["api_base"] == "https://provider.example.test/v1"
    assert "doctor-test-secret" not in raw_output
