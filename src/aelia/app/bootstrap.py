from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aelia.adapters.repository import SqliteAdapterRepository
from aelia.app.config import GateSettings, LlmProvider, Settings, load_settings
from aelia.app.logging import configure_json_logging
from aelia.contracts.adapter import AdapterMode, AdapterPolicyConfig
from aelia.llm.config import OpenAICompatibleConfig
from aelia.llm.openai_compatible import OpenAICompatibleLanguageGenerator
from aelia.models.autonomy import AutonomyPolicyConfig
from aelia.persona.loader import PersonaSourceLoader
from aelia.runtime.orchestrator import AutonomyOrchestrator
from aelia.runtime.ports import LanguageGeneratorPort, MockLanguageGenerator
from aelia.storage.database import Database
from aelia.storage.repositories import SqliteKernelRepository


@dataclass(frozen=True)
class RuntimeComposition:
    """All long-lived, platform-neutral runtime dependencies."""

    settings: Settings
    repository: SqliteKernelRepository
    adapter_repository: SqliteAdapterRepository
    processor: AutonomyOrchestrator


def build_autonomy_config(settings: Settings) -> AutonomyPolicyConfig:
    # Kept in the composition root so CLI and the HTTP backend cannot drift.
    return AutonomyPolicyConfig(
        policy_version="autonomy-config-v1",
        mode=settings.autonomy_mode,
        timezone=settings.autonomy_timezone,
        quiet_hours_enabled=settings.quiet_hours_enabled,
        quiet_start_hour=settings.quiet_start_hour,
        quiet_end_hour=settings.quiet_end_hour,
        actor_limit_per_hour=settings.proactive_actor_limit_per_hour,
        conversation_limit_per_hour=settings.proactive_conversation_limit_per_hour,
        daily_cost_budget=settings.proactive_daily_cost_budget,
        minimum_expected_value=settings.proactive_minimum_expected_value,
        high_drive_threshold=settings.high_drive_trigger_threshold,
    )


def build_adapter_policy(
    gate: GateSettings,
    *,
    conversation_id: str | None = None,
) -> AdapterPolicyConfig:
    allowlist = gate.allowed_conversation_ids
    if allowlist == ("-1",):
        if conversation_id is None or not conversation_id.strip():
            raise ValueError("wildcard gate policy requires an inbound conversation id")
        allowlist = (conversation_id,)
    mode = gate.mode
    # A disabled send switch is a hard backend-side shadow boundary as well as
    # a local gate-side safety check. This prevents queued live commands when a
    # gate is intentionally running in dry-run mode.
    if not gate.send_enabled and mode is AdapterMode.EXTERNAL_CANARY:
        mode = AdapterMode.SHADOW
    return AdapterPolicyConfig(
        policy_version=f"gate-policy:{gate.adapter_id}:v1",
        mode=mode,
        canary_conversation_ids=allowlist,
        conversation_limit_per_hour=gate.max_sends_per_hour,
    )


def build_language_generator(settings: Settings) -> LanguageGeneratorPort:
    if settings.llm_provider is LlmProvider.MOCK:
        return MockLanguageGenerator()
    if settings.llm_api_base is None or settings.llm_api_key is None or settings.llm_model is None:
        raise RuntimeError("validated OpenAI-compatible configuration is incomplete")
    return OpenAICompatibleLanguageGenerator(
        OpenAICompatibleConfig(
            api_base=settings.llm_api_base,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_attempts=settings.llm_max_attempts,
            max_output_tokens=settings.llm_max_output_tokens,
            structured_output_mode=settings.llm_structured_output_mode,
            allow_plain_text_fallback=settings.llm_allow_plain_text_fallback,
            thinking_mode=settings.llm_thinking_mode,
        )
    )


def build_composition(settings: Settings | None = None) -> RuntimeComposition:
    resolved = settings or load_settings()
    configure_json_logging(resolved.log_level.value)
    database = Database(
        path=resolved.database_path,
        busy_timeout_ms=resolved.sqlite_busy_timeout_ms,
    )
    repository = SqliteKernelRepository(
        database,
        conversation_buffer_limit=resolved.conversation_buffer_limit,
        recent_participation_limit=resolved.recent_participation_limit,
    )
    adapter_repository = SqliteAdapterRepository(database)
    specification = PersonaSourceLoader(resolved.persona_manifest_path).load_specification()
    processor = AutonomyOrchestrator(
        repository,
        agent_actor_id=resolved.agent_actor_id,
        persona_specification=specification,
        autonomy_config=build_autonomy_config(resolved),
        language_generator=build_language_generator(resolved),
    )
    return RuntimeComposition(
        settings=resolved,
        repository=repository,
        adapter_repository=adapter_repository,
        processor=processor,
    )


async def initialize_composition(composition: RuntimeComposition) -> None:
    # Both repositories share one Database. Initialization is idempotent and the
    # explicit calls document that the backend owns persistence lifecycle.
    await composition.repository.initialize()
    await composition.adapter_repository.initialize()


def resolve_path(path: Path, *, base: Path | None = None) -> Path:
    candidate = path if path.is_absolute() else ((base or Path.cwd()) / path)
    return candidate.resolve()


__all__ = [
    "RuntimeComposition",
    "build_adapter_policy",
    "build_autonomy_config",
    "build_composition",
    "build_language_generator",
    "initialize_composition",
    "resolve_path",
]
