from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from aelia.adapters.conformance import ConnectorReadinessPolicy
from aelia.adapters.repository import (
    AdapterConflictError,
    SqliteAdapterRepository,
)
from aelia.adapters.runtime import RuntimeAdapter
from aelia.app.config import LlmProvider, Settings, load_settings
from aelia.app.logging import configure_json_logging, get_logger
from aelia.contracts.adapter import (
    AdapterDeliveryReceipt,
    AdapterInboundEnvelope,
    AdapterOutboundCommand,
    AdapterPolicyConfig,
)
from aelia.contracts.connector import (
    ConnectorCapabilities,
    ConnectorReadinessReport,
    ExternalDeliveryReceipt,
)
from aelia.contracts.events import InboundEvent
from aelia.llm.config import OpenAICompatibleConfig
from aelia.llm.openai_compatible import (
    OpenAICompatibleLanguageGenerator,
)
from aelia.models.autonomy import AutonomyPolicyConfig
from aelia.persona.loader import PersonaIntegrityError, PersonaSourceLoader
from aelia.runtime.observability import TraceObservabilityService
from aelia.runtime.orchestrator import AutonomyOrchestrator
from aelia.runtime.ports import (
    FixedTextLanguageGenerator,
    LanguageGeneratorPort,
    MockLanguageGenerator,
)
from aelia.runtime.replay import ReplayService
from aelia.storage.database import Database
from aelia.storage.repositories import (
    EventConflictError,
    RecordNotFoundError,
    SqliteKernelRepository,
)

LOGGER = get_logger("cli")


def _json_output(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aelia")
    subcommands = parser.add_subparsers(dest="command", required=True)

    config = subcommands.add_parser("config", help="Inspect resolved V2 configuration")
    config_subcommands = config.add_subparsers(dest="config_command", required=True)
    config_subcommands.add_parser("doctor", help="Validate config and persona integrity")

    llm = subcommands.add_parser("llm", help="Inspect the configured language model provider")
    llm_subcommands = llm.add_subparsers(dest="llm_command", required=True)
    llm_doctor = llm_subcommands.add_parser(
        "doctor",
        help="Validate redacted LLM configuration and optionally probe /models",
    )
    llm_doctor.add_argument(
        "--probe",
        action="store_true",
        help="Make one authenticated GET request to the provider /models endpoint",
    )

    database = subcommands.add_parser("db", help="Manage the V2 SQLite database")
    database_subcommands = database.add_subparsers(dest="db_command", required=True)
    database_subcommands.add_parser("init", help="Apply all database migrations")

    event = subcommands.add_parser("event", help="Ingest versioned inbound events")
    event_subcommands = event.add_subparsers(dest="event_command", required=True)
    ingest = event_subcommands.add_parser("ingest", help="Ingest an event JSON file or stdin")
    ingest.add_argument("path", help="JSON file path or '-' for stdin")

    cycle = subcommands.add_parser("cycle", help="Inspect and replay cognitive cycles")
    cycle_subcommands = cycle.add_subparsers(dest="cycle_command", required=True)
    inspect_cycle = cycle_subcommands.add_parser("inspect", help="Inspect a persisted cycle")
    inspect_cycle.add_argument("cycle_id")
    replay_cycle = cycle_subcommands.add_parser("replay", help="Replay a persisted cycle")
    replay_cycle.add_argument("cycle_id")
    compare_cycles = cycle_subcommands.add_parser(
        "compare",
        help="Compare two persisted cycle traces",
    )
    compare_cycles.add_argument("left_cycle_id")
    compare_cycles.add_argument("right_cycle_id")
    export_cycle = cycle_subcommands.add_parser(
        "export",
        help="Export an event and cycle trace; private data is redacted by default",
    )
    export_cycle.add_argument("cycle_id")
    export_cycle.add_argument("path", help="Output JSON path or '-' for stdout")
    export_cycle.add_argument(
        "--include-private",
        action="store_true",
        help="Export private identifiers and content without redaction",
    )

    adapter = subcommands.add_parser(
        "adapter",
        help="Use the versioned language-neutral CLI adapter",
    )
    adapter_subcommands = adapter.add_subparsers(
        dest="adapter_command",
        required=True,
    )
    adapter_subcommands.add_parser(
        "schema",
        help="Print adapter ingress, command, and receipt JSON schemas",
    )
    connector_preflight = adapter_subcommands.add_parser(
        "connector-preflight",
        help="Validate a future external connector capability manifest",
    )
    connector_preflight.add_argument("path", help="Connector capability JSON path or '-'")
    adapter_ingest = adapter_subcommands.add_parser(
        "ingest",
        help="Ingest an adapter envelope JSON file or stdin",
    )
    adapter_ingest.add_argument("path", help="JSON file path or '-' for stdin")
    adapter_ingest.add_argument(
        "--test-content",
        help="Explicit fixed output for allowlisted test-canary simulation",
    )
    external_receipt = adapter_subcommands.add_parser(
        "external-receipt",
        help="Finalize a queued external-canary command with connector evidence",
    )
    external_receipt.add_argument("path", help="External receipt JSON path or '-'")
    adapter_subcommands.add_parser(
        "recover",
        help="Resume pending test-canary outbox dispatches",
    )

    return parser


def _load_event(path: str) -> InboundEvent:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return InboundEvent.model_validate_json(raw)


def _load_adapter_envelope(path: str) -> AdapterInboundEnvelope:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return AdapterInboundEnvelope.model_validate_json(raw)


def _load_connector_capabilities(path: str) -> ConnectorCapabilities:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return ConnectorCapabilities.model_validate_json(raw)


def _load_external_receipt(path: str) -> ExternalDeliveryReceipt:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return ExternalDeliveryReceipt.model_validate_json(raw)


def _build_repository(settings: Settings) -> SqliteKernelRepository:
    database = Database(
        path=settings.database_path,
        busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )
    return SqliteKernelRepository(
        database,
        conversation_buffer_limit=settings.conversation_buffer_limit,
        recent_participation_limit=settings.recent_participation_limit,
    )


def _build_autonomy_config(settings: Settings) -> AutonomyPolicyConfig:
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


def _build_adapter_config(settings: Settings) -> AdapterPolicyConfig:
    return AdapterPolicyConfig(
        policy_version="adapter-config-v1",
        mode=settings.adapter_mode,
        canary_conversation_ids=settings.adapter_canary_conversation_ids,
        conversation_limit_per_hour=settings.adapter_conversation_limit_per_hour,
    )


def _build_language_generator(settings: Settings) -> LanguageGeneratorPort:
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


async def _run(args: argparse.Namespace) -> int:
    settings = load_settings()
    configure_json_logging(settings.log_level.value)

    if args.command == "config" and args.config_command == "doctor":
        loader = PersonaSourceLoader(settings.persona_manifest_path)
        integrity = loader.verify_sources()
        specification = loader.load_specification()
        scenarios = loader.load_scenario_catalog()
        print(
            _json_output(
                {
                    "config": settings.resolved_redacted(),
                    "persona_integrity": integrity.model_dump(mode="json"),
                    "persona_specification": {
                        "version": specification.specification_version,
                        "rule_count": len(specification.all_rules()),
                        "scenario_count": len(scenarios.scenarios),
                    },
                }
            )
        )
        return 0 if integrity.valid else 1

    if args.command == "llm" and args.llm_command == "doctor":
        redacted_config = {
            "provider": settings.llm_provider.value,
            "api_base": settings.llm_api_base,
            "api_key_configured": settings.llm_api_key is not None,
            "model": settings.llm_model,
            "timeout_seconds": settings.llm_timeout_seconds,
            "max_attempts": settings.llm_max_attempts,
            "max_output_tokens": settings.llm_max_output_tokens,
            "structured_output_mode": settings.llm_structured_output_mode.value,
            "allow_plain_text_fallback": settings.llm_allow_plain_text_fallback,
            "thinking_mode": settings.llm_thinking_mode.value,
        }
        if settings.llm_provider is LlmProvider.MOCK:
            print(
                _json_output(
                    {
                        "configured": False,
                        "config": redacted_config,
                        "probe": None,
                    }
                )
            )
            return 0
        generator = _build_language_generator(settings)
        if not isinstance(generator, OpenAICompatibleLanguageGenerator):
            raise RuntimeError("unexpected language generator type")
        probe = await generator.probe() if args.probe else None
        print(
            _json_output(
                {
                    "configured": True,
                    "config": redacted_config,
                    "probe": probe.model_dump(mode="json") if probe is not None else None,
                }
            )
        )
        return 0 if probe is None or probe.reachable else 1

    if args.command == "adapter" and args.adapter_command == "schema":
        print(
            _json_output(
                {
                    "inbound_envelope": AdapterInboundEnvelope.model_json_schema(),
                    "outbound_command": AdapterOutboundCommand.model_json_schema(),
                    "delivery_receipt": AdapterDeliveryReceipt.model_json_schema(),
                    "external_connector_capabilities": (ConnectorCapabilities.model_json_schema()),
                    "external_delivery_receipt": (ExternalDeliveryReceipt.model_json_schema()),
                    "external_readiness_report": (ConnectorReadinessReport.model_json_schema()),
                }
            )
        )
        return 0

    if args.command == "adapter" and args.adapter_command == "connector-preflight":
        report = ConnectorReadinessPolicy().evaluate(_load_connector_capabilities(args.path))
        print(_json_output(report.model_dump(mode="json")))
        return 0 if report.ready_for_authorized_canary else 1

    repository = _build_repository(settings)
    await repository.initialize()

    if args.command == "adapter" and args.adapter_command == "external-receipt":
        adapter_repository = SqliteAdapterRepository(repository.database)
        dispatch = await adapter_repository.finalize_external_dispatch(
            _load_external_receipt(args.path)
        )
        LOGGER.info(
            "external_delivery_receipt_recorded",
            extra={
                "command_id": dispatch.command.command_id,
                "delivery_status": (
                    dispatch.receipt.status.value if dispatch.receipt is not None else "missing"
                ),
            },
        )
        print(_json_output(dispatch.model_dump(mode="json")))
        return 0

    if args.command == "db" and args.db_command == "init":
        print(
            _json_output(
                {
                    "database_path": str(settings.database_path),
                    "status": "initialized",
                }
            )
        )
        return 0

    if args.command == "event" and args.event_command == "ingest":
        event = _load_event(args.path)
        specification = PersonaSourceLoader(settings.persona_manifest_path).load_specification()
        orchestrator = AutonomyOrchestrator(
            repository,
            agent_actor_id=settings.agent_actor_id,
            persona_specification=specification,
            autonomy_config=_build_autonomy_config(settings),
            language_generator=_build_language_generator(settings),
        )
        process_result = await orchestrator.process(event)
        LOGGER.info(
            "cycle_processed",
            extra={
                "cycle_id": process_result.trace.cycle_id,
                "cycle_status": process_result.trace.status.value,
                "duplicate": process_result.duplicate,
                "event_id": event.event_id,
            },
        )
        print(
            _json_output(
                {
                    "duplicate": process_result.duplicate,
                    "trace": process_result.trace.model_dump(mode="json"),
                }
            )
        )
        return 0

    if args.command == "cycle" and args.cycle_command == "inspect":
        trace = await repository.get_cycle(args.cycle_id)
        print(_json_output(trace.model_dump(mode="json")))
        return 0

    if args.command == "cycle" and args.cycle_command == "replay":
        specification = PersonaSourceLoader(settings.persona_manifest_path).load_specification()
        replay_result = await ReplayService(
            repository,
            persona_specification=specification,
        ).replay_cycle(args.cycle_id)
        LOGGER.info(
            "cycle_replayed",
            extra={
                "cycle_id": replay_result.cycle_id,
                "event_id": replay_result.event_id,
                "matched": replay_result.matched,
            },
        )
        print(_json_output(replay_result.model_dump(mode="json")))
        return 0 if replay_result.matched else 1

    if args.command == "cycle" and args.cycle_command == "compare":
        comparison = await TraceObservabilityService(repository).compare_cycles(
            args.left_cycle_id,
            args.right_cycle_id,
        )
        print(_json_output(comparison.model_dump(mode="json")))
        return 0

    if args.command == "cycle" and args.cycle_command == "export":
        package = await TraceObservabilityService(repository).export_cycle(
            args.cycle_id,
            redact_private_data=not args.include_private,
        )
        output = _json_output(package.model_dump(mode="json"))
        if args.path == "-":
            print(output)
        else:
            Path(args.path).write_text(f"{output}\n", encoding="utf-8")
            print(
                _json_output(
                    {
                        "cycle_id": args.cycle_id,
                        "path": args.path,
                        "private_data_redacted": package.private_data_redacted,
                        "status": "exported",
                    }
                )
            )
        return 0

    if args.command == "adapter" and args.adapter_command in {"ingest", "recover"}:
        specification = PersonaSourceLoader(settings.persona_manifest_path).load_specification()
        test_content = (
            args.test_content
            if args.adapter_command == "ingest" and hasattr(args, "test_content")
            else None
        )
        if test_content is not None and settings.adapter_mode.value != "test_canary":
            raise ValueError("--test-content requires AELIA_ADAPTER_MODE=test_canary")
        orchestrator = AutonomyOrchestrator(
            repository,
            agent_actor_id=settings.agent_actor_id,
            persona_specification=specification,
            autonomy_config=_build_autonomy_config(settings),
            language_generator=(
                FixedTextLanguageGenerator(test_content)
                if test_content is not None
                else _build_language_generator(settings)
            ),
        )
        adapter_repository = SqliteAdapterRepository(repository.database)
        adapter = RuntimeAdapter(
            processor=orchestrator,
            kernel_repository=repository,
            adapter_repository=adapter_repository,
            config=_build_adapter_config(settings),
        )
        await adapter.initialize()
        if args.adapter_command == "ingest":
            adapter_result = await adapter.ingest(_load_adapter_envelope(args.path))
            LOGGER.info(
                "adapter_ingress_processed",
                extra={
                    "cycle_id": adapter_result.trace.cycle_id,
                    "cycle_status": adapter_result.trace.status.value,
                    "delivery_id": adapter_result.ingress.delivery_id,
                    "dispatch_outcome": (
                        adapter_result.dispatch.decision.outcome.value
                        if adapter_result.dispatch is not None
                        else "none"
                    ),
                    "duplicate": adapter_result.ingress_duplicate,
                    "event_id": adapter_result.trace.event_id,
                },
            )
            print(
                _json_output(
                    {
                        "kernel_duplicate": adapter_result.kernel_duplicate,
                        "ingress_duplicate": adapter_result.ingress_duplicate,
                        "ingress": adapter_result.ingress.model_dump(mode="json"),
                        "trace": adapter_result.trace.model_dump(mode="json"),
                        "dispatch": (
                            adapter_result.dispatch.model_dump(mode="json")
                            if adapter_result.dispatch is not None
                            else None
                        ),
                    }
                )
            )
            return 0
        recovered = await adapter.recover_pending()
        LOGGER.info(
            "adapter_recovery_completed",
            extra={"recovered_count": len(recovered)},
        )
        print(
            _json_output(
                {
                    "recovered_count": len(recovered),
                    "dispatches": [record.model_dump(mode="json") for record in recovered],
                }
            )
        )
        return 0

    raise RuntimeError("unsupported command")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(_run(args)))
    except (
        EventConflictError,
        AdapterConflictError,
        PersonaIntegrityError,
        RecordNotFoundError,
        ValidationError,
        ValueError,
        OSError,
    ) as exc:
        LOGGER.error(
            "cli_command_failed",
            extra={"error_code": type(exc).__name__},
        )
        print(_json_output({"error": type(exc).__name__, "message": str(exc)}), file=sys.stderr)
        raise SystemExit(2) from exc
