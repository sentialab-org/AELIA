from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from polyverse.adapters.repository import SqliteAdapterRepository
from polyverse.adapters.runtime import CliKernelAdapter, MockAdapterTransport
from polyverse.contracts.actions import (
    LanguageGenerationResult,
    LanguageGenerationStatus,
    OutboundAction,
)
from polyverse.contracts.adapter import (
    CURRENT_ADAPTER_INBOUND_SCHEMA_VERSION,
    AdapterInboundEnvelope,
    AdapterMode,
    AdapterPolicyConfig,
)
from polyverse.contracts.events import (
    ChannelType,
    EventType,
    InboundEvent,
    PermissionContext,
    Platform,
    ReplyReference,
    SourceReference,
)
from polyverse.models.autonomy import (
    AutonomyMode,
    AutonomyPolicyConfig,
)
from polyverse.persona.loader import PersonaSourceLoader
from polyverse.persona.models import PersonaView
from polyverse.runtime.orchestrator import (
    ActionOrchestrator,
    AutonomyOrchestrator,
    CognitiveOrchestrator,
    FoundationOrchestrator,
    MemoryOrchestrator,
    ObservationOrchestrator,
    PersonaOrchestrator,
)
from polyverse.runtime.ports import ExecutionPort, LanguageGeneratorPort
from polyverse.storage.database import Database
from polyverse.storage.repositories import SqliteKernelRepository


def make_event(
    event_id: str = "event-001",
    content: str = "hello",
    *,
    conversation_id: str = "conversation-001",
    channel_type: ChannelType = ChannelType.GROUP,
    actor_id: str = "user-001",
    mentions: tuple[str, ...] = (),
    reply_to: ReplyReference | None = None,
    can_send_message: bool = True,
    can_reply: bool = True,
    event_type: EventType = EventType.MESSAGE_CREATED,
    occurred_at: datetime | None = None,
    is_private: bool = False,
    permission_scopes: tuple[str, ...] = (),
    source_adapter: str = "test-fixture",
) -> InboundEvent:
    return InboundEvent(
        schema_version="2.0.0",
        event_id=event_id,
        platform=Platform.TEST,
        conversation_id=conversation_id,
        channel_type=channel_type,
        actor_id=actor_id,
        occurred_at=occurred_at or datetime(2026, 7, 30, 0, 0, tzinfo=UTC),
        event_type=event_type,
        content=content,
        reply_to=reply_to,
        mentions=mentions,
        permissions=PermissionContext(
            can_send_message=can_send_message,
            can_reply=can_reply,
            can_react=True,
            is_private=is_private,
            scopes=permission_scopes,
        ),
        source_reference=SourceReference(
            adapter=source_adapter,
            raw_event_id=event_id,
        ),
    )


async def make_foundation(
    temporary_directory: Path,
) -> tuple[SqliteKernelRepository, FoundationOrchestrator]:
    database = Database(temporary_directory / "polyverse-test.db")
    repository = SqliteKernelRepository(database)
    orchestrator = FoundationOrchestrator(repository)
    await orchestrator.initialize()
    return repository, orchestrator


async def make_observation(
    temporary_directory: Path,
    *,
    agent_actor_id: str = "agent-001",
    conversation_buffer_limit: int = 100,
    recent_participation_limit: int = 10,
) -> tuple[SqliteKernelRepository, ObservationOrchestrator]:
    database = Database(temporary_directory / "polyverse-observation-test.db")
    repository = SqliteKernelRepository(
        database,
        conversation_buffer_limit=conversation_buffer_limit,
        recent_participation_limit=recent_participation_limit,
    )
    orchestrator = ObservationOrchestrator(
        repository,
        agent_actor_id=agent_actor_id,
    )
    await orchestrator.initialize()
    return repository, orchestrator


async def make_persona(
    temporary_directory: Path,
    *,
    agent_actor_id: str = "agent-001",
) -> tuple[SqliteKernelRepository, PersonaOrchestrator]:
    database = Database(temporary_directory / "polyverse-persona-test.db")
    repository = SqliteKernelRepository(database)
    project_root = Path(__file__).resolve().parents[1]
    specification = PersonaSourceLoader(
        project_root / "src/polyverse/persona/source/manifest.json",
        repository_root=project_root,
    ).load_specification()
    orchestrator = PersonaOrchestrator(
        repository,
        agent_actor_id=agent_actor_id,
        persona_specification=specification,
    )
    await orchestrator.initialize()
    return repository, orchestrator


async def make_cognitive(
    temporary_directory: Path,
    *,
    agent_actor_id: str = "agent-001",
) -> tuple[SqliteKernelRepository, CognitiveOrchestrator]:
    database = Database(temporary_directory / "polyverse-cognitive-test.db")
    repository = SqliteKernelRepository(database)
    project_root = Path(__file__).resolve().parents[1]
    specification = PersonaSourceLoader(
        project_root / "src/polyverse/persona/source/manifest.json",
        repository_root=project_root,
    ).load_specification()
    orchestrator = CognitiveOrchestrator(
        repository,
        agent_actor_id=agent_actor_id,
        persona_specification=specification,
    )
    await orchestrator.initialize()
    return repository, orchestrator


async def make_action(
    temporary_directory: Path,
    *,
    agent_actor_id: str = "agent-001",
    execution_port: ExecutionPort | None = None,
    language_generator: LanguageGeneratorPort | None = None,
) -> tuple[SqliteKernelRepository, ActionOrchestrator]:
    database = Database(temporary_directory / "polyverse-action-test.db")
    repository = SqliteKernelRepository(database)
    project_root = Path(__file__).resolve().parents[1]
    specification = PersonaSourceLoader(
        project_root / "src/polyverse/persona/source/manifest.json",
        repository_root=project_root,
    ).load_specification()
    orchestrator = ActionOrchestrator(
        repository,
        agent_actor_id=agent_actor_id,
        persona_specification=specification,
        execution_port=execution_port,
        language_generator=language_generator,
    )
    await orchestrator.initialize()
    return repository, orchestrator


async def make_memory(
    temporary_directory: Path,
    *,
    agent_actor_id: str = "agent-001",
    execution_port: ExecutionPort | None = None,
    language_generator: LanguageGeneratorPort | None = None,
) -> tuple[SqliteKernelRepository, MemoryOrchestrator]:
    database = Database(temporary_directory / "polyverse-memory-test.db")
    repository = SqliteKernelRepository(database)
    project_root = Path(__file__).resolve().parents[1]
    specification = PersonaSourceLoader(
        project_root / "src/polyverse/persona/source/manifest.json",
        repository_root=project_root,
    ).load_specification()
    orchestrator = MemoryOrchestrator(
        repository,
        agent_actor_id=agent_actor_id,
        persona_specification=specification,
        execution_port=execution_port,
        language_generator=language_generator,
    )
    await orchestrator.initialize()
    return repository, orchestrator


def make_autonomy_config(
    *,
    mode: AutonomyMode = AutonomyMode.SHADOW,
    quiet_hours_enabled: bool = False,
    actor_limit_per_hour: int = 2,
    conversation_limit_per_hour: int = 5,
    daily_cost_budget: float = 10.0,
    minimum_expected_value: float = 0.6,
    high_drive_threshold: float = 0.8,
) -> AutonomyPolicyConfig:
    return AutonomyPolicyConfig(
        policy_version="autonomy-config-test-v1",
        mode=mode,
        timezone="Asia/Ho_Chi_Minh",
        quiet_hours_enabled=quiet_hours_enabled,
        quiet_start_hour=22,
        quiet_end_hour=8,
        actor_limit_per_hour=actor_limit_per_hour,
        conversation_limit_per_hour=conversation_limit_per_hour,
        daily_cost_budget=daily_cost_budget,
        minimum_expected_value=minimum_expected_value,
        high_drive_threshold=high_drive_threshold,
    )


async def make_autonomy(
    temporary_directory: Path,
    *,
    agent_actor_id: str = "agent-001",
    autonomy_config: AutonomyPolicyConfig | None = None,
    execution_port: ExecutionPort | None = None,
    language_generator: LanguageGeneratorPort | None = None,
) -> tuple[SqliteKernelRepository, AutonomyOrchestrator]:
    database = Database(temporary_directory / "polyverse-autonomy-test.db")
    repository = SqliteKernelRepository(database)
    project_root = Path(__file__).resolve().parents[1]
    specification = PersonaSourceLoader(
        project_root / "src/polyverse/persona/source/manifest.json",
        repository_root=project_root,
    ).load_specification()
    orchestrator = AutonomyOrchestrator(
        repository,
        agent_actor_id=agent_actor_id,
        persona_specification=specification,
        autonomy_config=autonomy_config or make_autonomy_config(),
        execution_port=execution_port,
        language_generator=language_generator,
    )
    await orchestrator.initialize()
    return repository, orchestrator


class FixtureTextLanguageGenerator:
    async def generate(
        self,
        action: OutboundAction,
        *,
        event: InboundEvent,
        persona_view: PersonaView,
    ) -> LanguageGenerationResult:
        return LanguageGenerationResult(
            action_id=action.action_id,
            generator="fixture-text-language-generator-v1",
            status=LanguageGenerationStatus.GENERATED,
            content="Test-only adapter response.",
            selected_action_type=action.action_type,
            applied_constraints=action.content_plan.constraints,
            changed_participation=False,
            provider="fixture",
            attempts=1,
        )


def make_adapter_envelope(
    *,
    delivery_id: str = "delivery-001",
    event_id: str = "adapter-event-001",
    conversation_id: str = "adapter-conversation-001",
    channel_type: ChannelType = ChannelType.GROUP,
) -> AdapterInboundEnvelope:
    adapter_id = "cli-test-adapter"
    event = make_event(
        event_id=event_id,
        conversation_id=conversation_id,
        channel_type=channel_type,
        content="can you help with this?",
        mentions=("agent-001",),
        source_adapter=adapter_id,
    )
    return AdapterInboundEnvelope(
        schema_version=CURRENT_ADAPTER_INBOUND_SCHEMA_VERSION,
        delivery_id=delivery_id,
        idempotency_key=f"ingress:{delivery_id}",
        adapter_id=adapter_id,
        received_at=event.occurred_at,
        event=event,
    )


async def make_adapter(
    temporary_directory: Path,
    *,
    mode: AdapterMode = AdapterMode.SHADOW,
    canary_conversation_ids: tuple[str, ...] = (),
    conversation_limit_per_hour: int = 5,
    language_generator: LanguageGeneratorPort | None = None,
) -> tuple[
    SqliteKernelRepository,
    AutonomyOrchestrator,
    SqliteAdapterRepository,
    CliKernelAdapter,
    MockAdapterTransport,
]:
    database = Database(temporary_directory / "polyverse-adapter-test.db")
    kernel_repository = SqliteKernelRepository(database)
    project_root = Path(__file__).resolve().parents[1]
    specification = PersonaSourceLoader(
        project_root / "src/polyverse/persona/source/manifest.json",
        repository_root=project_root,
    ).load_specification()
    orchestrator = AutonomyOrchestrator(
        kernel_repository,
        agent_actor_id="agent-001",
        persona_specification=specification,
        autonomy_config=make_autonomy_config(),
        language_generator=language_generator or FixtureTextLanguageGenerator(),
    )
    adapter_repository = SqliteAdapterRepository(database)
    transport = MockAdapterTransport()
    adapter = CliKernelAdapter(
        processor=orchestrator,
        kernel_repository=kernel_repository,
        adapter_repository=adapter_repository,
        config=AdapterPolicyConfig(
            policy_version="adapter-config-test-v1",
            mode=mode,
            canary_conversation_ids=canary_conversation_ids,
            conversation_limit_per_hour=conversation_limit_per_hour,
        ),
        transport=transport,
    )
    await orchestrator.initialize()
    await adapter.initialize()
    return (
        kernel_repository,
        orchestrator,
        adapter_repository,
        adapter,
        transport,
    )
