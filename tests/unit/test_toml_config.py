from __future__ import annotations

from pathlib import Path

from polyverse.app.config import LlmProvider, load_settings
from polyverse.contracts.adapter import AdapterMode


def test_normal_configuration_loads_from_toml_and_dotenv_is_secrets_only(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[runtime]
environment = "test"
host = "127.0.0.1"
port = 9191
public_url = "http://127.0.0.1:9191"
log_level = "DEBUG"
max_request_bytes = 1048576

[storage]
database_path = "data/test.db"
persona_manifest_path = "src/polyverse/persona/source/manifest.json"
conversation_buffer_limit = 50
recent_participation_limit = 5
sqlite_busy_timeout_ms = 1000

[agent]
actor_id = "agent-from-toml"

[autonomy]
mode = "shadow"
timezone = "Asia/Ho_Chi_Minh"
quiet_hours_enabled = false
quiet_start_hour = 22
quiet_end_hour = 8
actor_limit_per_hour = 2
conversation_limit_per_hour = 5
daily_cost_budget = 10.0
minimum_expected_value = 0.6
high_drive_trigger_threshold = 0.8

[adapter]
mode = "shadow"
canary_conversation_ids = []
conversation_limit_per_hour = 5

[llm]
provider = "openai_compatible"
api_base = "https://provider.example.test/v1"
model = "provider/model"
timeout_seconds = 30
max_attempts = 2
max_output_tokens = 1024
structured_output_mode = "json_object"
allow_plain_text_fallback = true

[platforms.discord_selfbot]
enabled = true
adapter_id = "discord-selfbot-v2"
platform = "discord_selfbot"
mode = "external_canary"
allowed_conversation_ids = ["-1"]
allowed_actor_ids = []
send_enabled = true
max_sends_per_hour = 7
state_path = "data/selfbot.jsonl"
request_timeout_ms = 120000
""".strip()
        + "\n",
        encoding="utf-8",
    )
    env_path = tmp_path / ".env"
    env_path.write_text(
        "POLYVERSE_LLM_API_KEY=test-secret\nPOLYVERSE_AGENT_ACTOR_ID=must-not-override-toml\n",
        encoding="utf-8",
    )

    settings = load_settings(config_path=config_path, env_file=env_path)

    assert settings.runtime_port == 9191
    assert settings.agent_actor_id == "agent-from-toml"
    assert settings.llm_provider is LlmProvider.OPENAI_COMPATIBLE
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "test-secret"
    assert settings.llm_allow_plain_text_fallback is True
    gate = settings.platforms["discord_selfbot"]
    assert gate.mode is AdapterMode.EXTERNAL_CANARY
    assert gate.allowed_conversation_ids == ("-1",)
    assert gate.send_enabled is True


def test_checked_in_config_example_is_loadable() -> None:
    project_root = Path(__file__).resolve().parents[2]
    settings = load_settings(
        config_path=project_root / "config.example.toml",
        env_file=project_root / ".env.example",
    )

    assert settings.llm_provider is LlmProvider.MOCK
    assert settings.runtime_port == 8787
    assert settings.platforms["discord_selfbot"].enabled is False
