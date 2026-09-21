from __future__ import annotations

from pathlib import Path

from polyverse.adapters.conformance import ConnectorReadinessPolicy
from polyverse.contracts.connector import (
    CURRENT_CONNECTOR_CAPABILITY_SCHEMA_VERSION,
    ConnectorCapabilities,
)
from polyverse.contracts.events import Platform

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _capabilities(**updates: object) -> ConnectorCapabilities:
    values: dict[str, object] = {
        "schema_version": CURRENT_CONNECTOR_CAPABILITY_SCHEMA_VERSION,
        "connector_id": "candidate-connector",
        "connector_version": "0.1.0",
        "platform": Platform.DISCORD,
        "account_model": "authorized-test-account",
        "inbound_schema_version": "1.0.0",
        "outbound_schema_version": "1.1.0",
        "receipt_schema_version": "2.0.0",
        "supports_idempotency_lookup": True,
        "supports_canary_allowlist": True,
        "supports_kill_switch": True,
        "supports_reconnect_cursor": True,
        "supports_permission_probe": True,
        "supports_rate_limit_observation": True,
        "redacts_secrets": True,
    }
    values.update(updates)
    return ConnectorCapabilities.model_validate(values)


def test_complete_connector_capability_set_passes_static_preflight() -> None:
    report = ConnectorReadinessPolicy().evaluate(_capabilities())

    assert report.ready_for_authorized_canary is True
    assert all(check.passed for check in report.checks)


def test_missing_connector_capability_blocks_static_preflight_with_reason() -> None:
    report = ConnectorReadinessPolicy().evaluate(
        _capabilities(
            supports_idempotency_lookup=False,
            supports_permission_probe=False,
        )
    )

    failed = {check.code for check in report.checks if not check.passed}
    assert report.ready_for_authorized_canary is False
    assert failed == {"idempotency_lookup", "permission_probe"}


def test_all_active_connector_manifests_pass_static_preflight() -> None:
    expected = {
        "discord-selfbot": ("discord-selfbot-v2", Platform.DISCORD_SELFBOT),
        "discord-officialbot": ("discord-officialbot-v2", Platform.DISCORD),
        "telegram-officialbot": ("telegram-officialbot-v2", Platform.TELEGRAM),
    }

    for directory, (connector_id, platform) in expected.items():
        capabilities = ConnectorCapabilities.model_validate_json(
            (PROJECT_ROOT / "platforms" / directory / "capabilities.json").read_text(
                encoding="utf-8"
            )
        )
        report = ConnectorReadinessPolicy().evaluate(capabilities)

        assert capabilities.connector_id == connector_id
        assert capabilities.platform is platform
        assert report.ready_for_authorized_canary is True
