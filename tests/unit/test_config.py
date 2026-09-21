from __future__ import annotations

import json

import pytest
from pydantic import SecretStr, ValidationError

from aelia.app.config import LlmProvider, Settings
from aelia.contracts.adapter import AdapterMode


def test_unknown_configuration_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Settings.model_validate({"unknown_setting": "value"})


@pytest.mark.parametrize("agent_actor_id", ["", "   ", " agent-001", "agent-001 "])
def test_agent_actor_id_must_be_canonical(agent_actor_id: str) -> None:
    with pytest.raises(ValidationError):
        Settings(agent_actor_id=agent_actor_id)


def test_resolved_configuration_contains_only_declared_non_secret_values() -> None:
    settings = Settings(
        agent_actor_id="agent-001",
        conversation_buffer_limit=200,
        recent_participation_limit=20,
    )

    resolved = settings.resolved_redacted()

    assert resolved["agent_actor_id"] == "agent-001"
    assert resolved["conversation_buffer_limit"] == 200
    assert resolved["recent_participation_limit"] == 20
    assert set(resolved) == (set(Settings.model_fields) - {"llm_api_key"}) | {
        "llm_api_key_configured"
    }
    assert "llm_api_key" not in resolved


def test_autonomy_timezone_and_quiet_window_are_validated() -> None:
    with pytest.raises(ValidationError, match="valid IANA timezone"):
        Settings(autonomy_timezone="Mars/Olympus")
    with pytest.raises(ValidationError, match="distinct start and end"):
        Settings(
            quiet_hours_enabled=True,
            quiet_start_hour=8,
            quiet_end_hour=8,
        )


def test_canary_configuration_requires_unique_allowlist() -> None:
    with pytest.raises(ValidationError, match="requires a conversation allowlist"):
        Settings(adapter_mode=AdapterMode.TEST_CANARY)
    with pytest.raises(ValidationError, match="requires a conversation allowlist"):
        Settings(adapter_mode=AdapterMode.EXTERNAL_CANARY)
    with pytest.raises(ValidationError, match="must be unique"):
        Settings(
            adapter_mode=AdapterMode.TEST_CANARY,
            adapter_canary_conversation_ids=("one", "one"),
        )


def test_openai_compatible_configuration_requires_and_redacts_credentials() -> None:
    with pytest.raises(ValidationError, match="requires llm_api_base"):
        Settings(
            _env_file=None,
            llm_provider=LlmProvider.OPENAI_COMPATIBLE,
        )

    settings = Settings(
        _env_file=None,
        llm_provider=LlmProvider.OPENAI_COMPATIBLE,
        llm_api_base="https://provider.example.test/v1/",
        llm_api_key=SecretStr("top-secret"),
        llm_model="provider/model",
    )
    resolved_json = json.dumps(settings.resolved_redacted())

    assert settings.llm_api_base == "https://provider.example.test/v1"
    assert settings.resolved_redacted()["llm_api_key_configured"] is True
    assert "top-secret" not in resolved_json


@pytest.mark.parametrize(
    "api_base",
    [
        "provider.example.test/v1",
        "https://user:pass@provider.example.test/v1",
        "https://provider.example.test/v1?key=value",
        "https://provider.example.test/v1#fragment",
    ],
)
def test_llm_api_base_rejects_unsafe_or_ambiguous_urls(api_base: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            llm_provider=LlmProvider.OPENAI_COMPATIBLE,
            llm_api_base=api_base,
            llm_api_key=SecretStr("test-key"),
            llm_model="test-model",
        )
