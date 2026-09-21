from __future__ import annotations

from pathlib import Path

from aelia.app.config import Environment, Settings
from aelia.contracts.adapter import AdapterMode
from aelia.models.autonomy import AutonomyMode

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _declared_names(path: Path) -> set[str]:
    return {
        line.split("=", 1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    }


def test_environment_example_is_complete_and_safe_by_default() -> None:
    settings = Settings(_env_file=PROJECT_ROOT / ".env.example")

    assert settings.environment is Environment.DEVELOPMENT
    assert settings.autonomy_mode is AutonomyMode.SHADOW
    assert settings.adapter_mode is AdapterMode.SHADOW
    assert settings.adapter_canary_conversation_ids == ()
    assert set(settings.resolved_redacted()) == (set(Settings.model_fields) - {"llm_api_key"}) | {
        "llm_api_key_configured"
    }


def test_all_environment_examples_contain_secrets_only() -> None:
    assert _declared_names(PROJECT_ROOT / ".env.example") == {
        "AELIA_LLM_API_KEY",
        "AELIA_RUNTIME_GATE_TOKEN",
    }
    assert _declared_names(PROJECT_ROOT / "platforms/discord-selfbot/.env.example") == {
        "DISCORD_SELFBOT_TOKEN",
        "AELIA_RUNTIME_GATE_TOKEN",
    }
    assert _declared_names(PROJECT_ROOT / "platforms/discord-officialbot/.env.example") == {
        "DISCORD_BOT_TOKEN",
        "AELIA_RUNTIME_GATE_TOKEN",
    }
    assert _declared_names(PROJECT_ROOT / "platforms/telegram-officialbot/.env.example") == {
        "TELEGRAM_BOT_TOKEN",
        "AELIA_RUNTIME_GATE_TOKEN",
    }
