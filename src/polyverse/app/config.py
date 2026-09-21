from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from polyverse.contracts.adapter import AdapterMode
from polyverse.contracts.events import Platform
from polyverse.llm.config import LlmStructuredOutputMode, LlmThinkingMode
from polyverse.models.autonomy import AutonomyMode


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LlmProvider(StrEnum):
    MOCK = "mock"
    OPENAI_COMPATIBLE = "openai_compatible"


class GateSettings(BaseModel):
    """Non-secret configuration for one independently running platform gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    adapter_id: str = Field(min_length=1, max_length=128)
    platform: Platform
    mode: AdapterMode = AdapterMode.SHADOW
    allowed_conversation_ids: tuple[str, ...] = ()
    allowed_actor_ids: tuple[str, ...] = ()
    send_enabled: bool = False
    max_sends_per_hour: int = Field(default=5, ge=1, le=1_000)
    state_path: Path = Path("data/v2/gate-journal.jsonl")
    request_timeout_ms: int = Field(default=180_000, ge=1_000, le=600_000)
    api_base: str | None = None
    poll_timeout_seconds: int = Field(default=30, ge=1, le=50)

    @field_validator("adapter_id")
    @classmethod
    def reject_blank_adapter_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or normalized != value:
            raise ValueError("adapter_id must be non-blank and have no surrounding whitespace")
        return normalized

    @field_validator("allowed_conversation_ids", "allowed_actor_ids")
    @classmethod
    def normalize_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("gate identifier allowlists must not contain blank values")
        if len(normalized) != len(set(normalized)):
            raise ValueError("gate identifier allowlists must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_wildcard(self) -> GateSettings:
        if "-1" in self.allowed_conversation_ids and len(self.allowed_conversation_ids) != 1:
            raise ValueError("conversation wildcard -1 must be used alone")
        if self.mode in {AdapterMode.TEST_CANARY, AdapterMode.EXTERNAL_CANARY} and not (
            self.allowed_conversation_ids
        ):
            raise ValueError("canary gate mode requires a conversation allowlist")
        if self.send_enabled and self.mode is not AdapterMode.EXTERNAL_CANARY:
            raise ValueError("send-enabled gate requires external_canary mode")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="POLYVERSE_",
        extra="forbid",
        case_sensitive=False,
    )

    environment: Environment = Environment.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO
    runtime_host: str = "127.0.0.1"
    runtime_port: int = Field(default=8787, ge=1, le=65_535)
    runtime_public_url: str = "http://127.0.0.1:8787"
    runtime_max_request_bytes: int = Field(default=5 * 1024 * 1024, ge=1_024, le=50 * 1024 * 1024)
    database_path: Path = Path("data/v2/polyverse.db")
    persona_manifest_path: Path = Path("src/polyverse/persona/source/manifest.json")
    agent_actor_id: str = Field(default="polyverse-agent", min_length=1, max_length=256)
    conversation_buffer_limit: int = Field(default=100, ge=10, le=10_000)
    recent_participation_limit: int = Field(default=10, ge=1, le=1_000)
    sqlite_busy_timeout_ms: int = Field(default=5_000, ge=100, le=120_000)
    autonomy_mode: AutonomyMode = AutonomyMode.SHADOW
    autonomy_timezone: str = "Asia/Ho_Chi_Minh"
    quiet_hours_enabled: bool = True
    quiet_start_hour: int = Field(default=22, ge=0, le=23)
    quiet_end_hour: int = Field(default=8, ge=0, le=23)
    proactive_actor_limit_per_hour: int = Field(default=2, ge=1, le=1_000)
    proactive_conversation_limit_per_hour: int = Field(
        default=5,
        ge=1,
        le=10_000,
    )
    proactive_daily_cost_budget: float = Field(default=10.0, gt=0.0)
    proactive_minimum_expected_value: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
    )
    high_drive_trigger_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    adapter_mode: AdapterMode = AdapterMode.SHADOW
    adapter_canary_conversation_ids: tuple[str, ...] = ()
    adapter_conversation_limit_per_hour: int = Field(
        default=5,
        ge=1,
        le=10_000,
    )
    llm_provider: LlmProvider = LlmProvider.MOCK
    llm_api_base: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = Field(default=60.0, ge=1.0, le=300.0)
    llm_max_attempts: int = Field(default=3, ge=1, le=5)
    llm_max_output_tokens: int = Field(default=512, ge=32, le=16_384)
    llm_structured_output_mode: LlmStructuredOutputMode = LlmStructuredOutputMode.JSON_OBJECT
    llm_allow_plain_text_fallback: bool = False
    llm_thinking_mode: LlmThinkingMode = LlmThinkingMode.AUTO
    platforms: dict[str, GateSettings] = Field(default_factory=dict)

    _runtime_gate_token: SecretStr | None = PrivateAttr(default=None)

    @field_validator("agent_actor_id")
    @classmethod
    def reject_blank_agent_actor_id(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("agent_actor_id must be non-blank and have no surrounding whitespace")
        return value

    @field_validator("autonomy_timezone")
    @classmethod
    def require_valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("autonomy_timezone must be a valid IANA timezone") from exc
        return value

    @field_validator("llm_api_base")
    @classmethod
    def validate_llm_api_base(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("llm_api_base must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "llm_api_base cannot contain credentials, a query string, or a fragment"
            )
        return normalized

    @field_validator("runtime_host")
    @classmethod
    def validate_runtime_host(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("runtime_host must not be blank")
        return normalized

    @field_validator("runtime_public_url")
    @classmethod
    def validate_runtime_public_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("runtime_public_url must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "runtime_public_url cannot contain credentials, a query string, or a fragment"
            )
        return normalized

    @field_validator("llm_model")
    @classmethod
    def validate_llm_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("llm_model must not be blank")
        if len(normalized) > 256:
            raise ValueError("llm_model exceeds 256 characters")
        return normalized

    @model_validator(mode="after")
    def validate_cross_field_configuration(self) -> Settings:
        if self.quiet_hours_enabled and self.quiet_start_hour == self.quiet_end_hour:
            raise ValueError("enabled quiet hours require distinct start and end hours")
        if (
            self.adapter_mode in {AdapterMode.TEST_CANARY, AdapterMode.EXTERNAL_CANARY}
            and not self.adapter_canary_conversation_ids
        ):
            raise ValueError("canary adapter mode requires a conversation allowlist")
        if len(self.adapter_canary_conversation_ids) != len(
            set(self.adapter_canary_conversation_ids)
        ):
            raise ValueError("adapter canary conversation ids must be unique")
        if self.llm_provider is LlmProvider.OPENAI_COMPATIBLE:
            missing = []
            if self.llm_api_base is None:
                missing.append("llm_api_base")
            if self.llm_api_key is None or not self.llm_api_key.get_secret_value().strip():
                missing.append("llm_api_key")
            if self.llm_model is None:
                missing.append("llm_model")
            if missing:
                raise ValueError("openai-compatible LLM provider requires " + ", ".join(missing))
        adapter_ids = [gate.adapter_id for gate in self.platforms.values()]
        if len(adapter_ids) != len(set(adapter_ids)):
            raise ValueError("platform gate adapter ids must be unique")
        return self

    def resolved_redacted(self) -> dict[str, Any]:
        """Return the effective non-secret configuration as JSON-safe values."""

        resolved = self.model_dump(mode="json", exclude={"llm_api_key"})
        resolved["llm_api_key_configured"] = self.llm_api_key is not None
        return resolved

    @property
    def runtime_gate_token(self) -> SecretStr | None:
        """Bearer token used only at the backend/gate protocol boundary."""

        return self._runtime_gate_token


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SECRET_ENV_NAMES = {"POLYVERSE_LLM_API_KEY", "POLYVERSE_RUNTIME_GATE_TOKEN"}


def _env_name(field_name: str) -> str:
    return "POLYVERSE_" + field_name.upper()


def _parse_env_override(field_name: str, raw: str) -> Any:
    if field_name in {"adapter_canary_conversation_ids"}:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return tuple(item.strip() for item in raw.split(",") if item.strip())
        return tuple(str(item) for item in parsed)
    return raw


def _read_secret_env_file(path: Path) -> dict[str, str]:
    """Read only the two supported secret names; never expose their values."""

    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        if name not in _SECRET_ENV_NAMES:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values


def _toml_settings_values(raw: Mapping[str, Any]) -> dict[str, Any]:
    runtime = raw.get("runtime", {})
    storage = raw.get("storage", {})
    agent = raw.get("agent", {})
    autonomy = raw.get("autonomy", {})
    adapter = raw.get("adapter", {})
    llm = raw.get("llm", {})
    values: dict[str, Any] = {
        "environment": runtime.get("environment", Environment.DEVELOPMENT.value),
        "log_level": runtime.get("log_level", LogLevel.INFO.value),
        "runtime_host": runtime.get("host", "127.0.0.1"),
        "runtime_port": runtime.get("port", 8787),
        "runtime_public_url": runtime.get("public_url", "http://127.0.0.1:8787"),
        "runtime_max_request_bytes": runtime.get("max_request_bytes", 5 * 1024 * 1024),
        "database_path": storage.get("database_path", "data/v2/polyverse.db"),
        "persona_manifest_path": storage.get(
            "persona_manifest_path", "src/polyverse/persona/source/manifest.json"
        ),
        "conversation_buffer_limit": storage.get("conversation_buffer_limit", 100),
        "recent_participation_limit": storage.get("recent_participation_limit", 10),
        "sqlite_busy_timeout_ms": storage.get("sqlite_busy_timeout_ms", 5_000),
        "agent_actor_id": agent.get("actor_id", "polyverse-agent"),
        "autonomy_mode": autonomy.get("mode", AutonomyMode.SHADOW.value),
        "autonomy_timezone": autonomy.get("timezone", "Asia/Ho_Chi_Minh"),
        "quiet_hours_enabled": autonomy.get("quiet_hours_enabled", True),
        "quiet_start_hour": autonomy.get("quiet_start_hour", 22),
        "quiet_end_hour": autonomy.get("quiet_end_hour", 8),
        "proactive_actor_limit_per_hour": autonomy.get("actor_limit_per_hour", 2),
        "proactive_conversation_limit_per_hour": autonomy.get("conversation_limit_per_hour", 5),
        "proactive_daily_cost_budget": autonomy.get("daily_cost_budget", 10.0),
        "proactive_minimum_expected_value": autonomy.get("minimum_expected_value", 0.6),
        "high_drive_trigger_threshold": autonomy.get("high_drive_trigger_threshold", 0.8),
        "adapter_mode": adapter.get("mode", AdapterMode.SHADOW.value),
        "adapter_canary_conversation_ids": tuple(adapter.get("canary_conversation_ids", ())),
        "adapter_conversation_limit_per_hour": adapter.get("conversation_limit_per_hour", 5),
        "llm_provider": llm.get("provider", LlmProvider.MOCK.value),
        "llm_api_base": llm.get("api_base"),
        "llm_model": llm.get("model"),
        "llm_timeout_seconds": llm.get("timeout_seconds", 60),
        "llm_max_attempts": llm.get("max_attempts", 3),
        "llm_max_output_tokens": llm.get("max_output_tokens", 512),
        "llm_structured_output_mode": llm.get("structured_output_mode", "json_object"),
        "llm_allow_plain_text_fallback": llm.get("allow_plain_text_fallback", False),
        "llm_thinking_mode": llm.get("thinking_mode", LlmThinkingMode.AUTO.value),
    }
    platforms: dict[str, GateSettings] = {}
    for name, section in (raw.get("platforms", {}) or {}).items():
        platforms[str(name)] = GateSettings.model_validate(section)
    values["platforms"] = platforms
    return values


def load_settings(
    *,
    config_path: Path | None = None,
    env_file: Path | None = None,
) -> Settings:
    """Load normal values from TOML and secrets from process/.env.

    The legacy ``Settings(...)`` constructor remains available for focused unit
    tests and compatibility. Runtime entry points should call this function so
    ordinary values cannot accidentally come from a secret file.
    """

    selected_config = config_path or Path(
        os.environ.get("POLYVERSE_CONFIG_FILE", _PROJECT_ROOT / "config.toml")
    )
    if not selected_config.is_absolute():
        selected_config = (_PROJECT_ROOT / selected_config).resolve()
    raw_config: dict[str, Any] = {}
    if selected_config.is_file():
        with selected_config.open("rb") as handle:
            raw_config = tomllib.load(handle)
    values = _toml_settings_values(raw_config)

    # Process environment values are deployment/test overrides. The dotenv file
    # is deliberately consulted only for secret names.
    for field_name in Settings.model_fields:
        if field_name == "platforms":
            continue
        name = _env_name(field_name)
        if name in os.environ:
            values[field_name] = _parse_env_override(field_name, os.environ[name])

    selected_env = env_file or (_PROJECT_ROOT / ".env")
    secret_values = _read_secret_env_file(selected_env)
    llm_key = os.environ.get("POLYVERSE_LLM_API_KEY", secret_values.get("POLYVERSE_LLM_API_KEY"))
    if llm_key is not None and llm_key.strip():
        values["llm_api_key"] = llm_key
    settings = Settings(_env_file=None, **values)
    runtime_token = os.environ.get(
        "POLYVERSE_RUNTIME_GATE_TOKEN",
        secret_values.get("POLYVERSE_RUNTIME_GATE_TOKEN"),
    )
    if runtime_token is not None and runtime_token.strip():
        settings._runtime_gate_token = SecretStr(runtime_token.strip())
    return settings
