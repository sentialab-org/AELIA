from __future__ import annotations

import json
from pathlib import Path

import httpx
from pydantic import SecretStr

from polyverse.contracts.actions import (
    ExecutionStatus,
    LanguageGenerationStatus,
)
from polyverse.contracts.traces import CycleStatus
from polyverse.llm.config import (
    LlmStructuredOutputMode,
    LlmThinkingMode,
    OpenAICompatibleConfig,
)
from polyverse.llm.openai_compatible import (
    OpenAICompatibleLanguageGenerator,
)
from polyverse.runtime.replay import ReplayService
from tests.helpers import make_action, make_event


async def _no_sleep(delay: float) -> None:
    assert delay > 0


def _generator(
    handler: httpx.MockTransport,
    *,
    max_attempts: int = 3,
) -> OpenAICompatibleLanguageGenerator:
    return OpenAICompatibleLanguageGenerator(
        OpenAICompatibleConfig(
            api_base="https://llm.example.test/v1",
            api_key=SecretStr("test-secret"),
            model="test-model",
            timeout_seconds=5,
            max_attempts=max_attempts,
            max_output_tokens=256,
            structured_output_mode=LlmStructuredOutputMode.JSON_SCHEMA,
        ),
        transport=handler,
        sleep=_no_sleep,
    )


async def test_openai_compatible_generation_is_structured_and_replayable(
    tmp_path: Path,
) -> None:
    seen_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://llm.example.test/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-secret"
        seen_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"x-request-id": "request-001"},
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": (
                                "```json\n"
                                + json.dumps(
                                    {"content": "Ừ, gửi đoạn lỗi đây xem nào."},
                                    ensure_ascii=False,
                                )
                                + "\n```"
                            ),
                        }
                    }
                ]
            },
        )

    repository, orchestrator = await make_action(
        tmp_path,
        language_generator=_generator(httpx.MockTransport(handler)),
    )
    event = make_event(
        event_id="openai-compatible-success",
        content="Mày xem giúp tao đoạn code này được không?",
        mentions=("agent-001",),
    )

    result = await orchestrator.process(event)

    assert seen_payload["model"] == "test-model"
    assert seen_payload["stream"] is False
    assert seen_payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "polyverse_language_realization",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 10_000,
                    }
                },
                "required": ["content"],
                "additionalProperties": False,
            },
        },
    }
    user_message = seen_payload["messages"][-1]  # type: ignore[index]
    assert isinstance(user_message, dict)
    prompt_input = json.loads(str(user_message["content"]))
    assert prompt_input["source_message"] == event.content
    assert prompt_input["persona"]["rules"]
    assert result.trace.schema_version == "2.3.0"
    assert result.trace.language_generation is not None
    assert result.trace.language_generation.status is LanguageGenerationStatus.GENERATED
    assert result.trace.language_generation.content == "Ừ, gửi đoạn lỗi đây xem nào."
    assert result.trace.language_generation.request_id == "request-001"
    assert result.trace.language_generation.attempts == 1
    assert result.trace.execution_result is not None
    assert result.trace.execution_result.status is ExecutionStatus.SIMULATED

    replay = await ReplayService(
        repository,
        persona_specification=orchestrator.persona_specification,
    ).replay_cycle(result.trace.cycle_id)
    assert replay.matched is True


async def test_openai_compatible_provider_retries_transient_status(
    tmp_path: Path,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": json.dumps({"content": "Thử lại thì được rồi."})}}
                ]
            },
        )

    _, orchestrator = await make_action(
        tmp_path,
        language_generator=_generator(httpx.MockTransport(handler)),
    )
    result = await orchestrator.process(
        make_event(
            event_id="openai-compatible-retry",
            content="check this",
            mentions=("agent-001",),
        )
    )

    assert calls == 2
    assert result.trace.language_generation is not None
    assert result.trace.language_generation.status is LanguageGenerationStatus.GENERATED
    assert result.trace.language_generation.attempts == 2


async def test_openai_compatible_retry_honors_retry_after_header(
    tmp_path: Path,
) -> None:
    calls = 0
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "7.5"},
                json={"error": {"message": "rate limited"}},
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"content": "Đã thử lại."})}}]},
        )

    generator = _generator(httpx.MockTransport(handler))
    generator.sleep = sleep
    _, orchestrator = await make_action(tmp_path, language_generator=generator)

    result = await orchestrator.process(
        make_event(
            event_id="openai-compatible-retry-after",
            content="check this",
            mentions=("agent-001",),
        )
    )

    assert calls == 2
    assert delays == [7.5]
    assert result.trace.language_generation is not None
    assert result.trace.language_generation.status is LanguageGenerationStatus.GENERATED


async def test_invalid_model_output_becomes_a_structured_failed_cycle(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    repository, orchestrator = await make_action(
        tmp_path,
        language_generator=_generator(httpx.MockTransport(handler)),
    )
    result = await orchestrator.process(
        make_event(
            event_id="openai-compatible-invalid-output",
            content="check this",
            mentions=("agent-001",),
        )
    )

    assert result.trace.status is CycleStatus.FAILED
    assert result.trace.language_generation is not None
    assert result.trace.language_generation.status is LanguageGenerationStatus.FAILED
    assert result.trace.language_generation.error_code == "invalid_structured_output"
    assert result.trace.language_generation.retryable is False
    assert result.trace.execution_result is not None
    assert result.trace.execution_result.status is ExecutionStatus.FAILED
    assert result.trace.execution_result.side_effect_performed is False
    assert result.trace.errors[0].code == "invalid_structured_output"

    replay = await ReplayService(
        repository,
        persona_specification=orchestrator.persona_specification,
    ).replay_cycle(result.trace.cycle_id)
    assert replay.matched is True


async def test_opt_in_plain_text_fallback_supports_compatible_providers(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Ừ, đường model đang chạy."}}]},
        )

    generator = _generator(httpx.MockTransport(handler))
    generator.config = generator.config.model_copy(update={"allow_plain_text_fallback": True})
    _, orchestrator = await make_action(tmp_path, language_generator=generator)

    result = await orchestrator.process(
        make_event(
            event_id="openai-compatible-plain-text-fallback",
            content="check this",
            mentions=("agent-001",),
        )
    )

    assert result.trace.status is CycleStatus.COMPLETED
    assert result.trace.language_generation is not None
    assert result.trace.language_generation.status is LanguageGenerationStatus.GENERATED
    assert result.trace.language_generation.content == "Ừ, đường model đang chạy."


async def test_ambiguous_read_timeout_is_not_blindly_retried(
    tmp_path: Path,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("ambiguous provider timeout", request=request)

    _, orchestrator = await make_action(
        tmp_path,
        language_generator=_generator(httpx.MockTransport(handler)),
    )
    result = await orchestrator.process(
        make_event(
            event_id="openai-compatible-read-timeout",
            content="check this",
            mentions=("agent-001",),
        )
    )

    assert calls == 1
    assert result.trace.language_generation is not None
    assert result.trace.language_generation.status is LanguageGenerationStatus.FAILED
    assert result.trace.language_generation.error_code == "ambiguous_transport_failure"
    assert result.trace.language_generation.retryable is False


async def test_provider_probe_never_returns_the_api_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://llm.example.test/v1/models"
        return httpx.Response(
            200,
            headers={"x-request-id": "probe-001"},
            json={"data": [{"id": "test-model"}]},
        )

    probe = await _generator(httpx.MockTransport(handler)).probe()
    serialized = probe.model_dump_json()

    assert probe.reachable is True
    assert probe.model_listed is True
    assert probe.request_id == "probe-001"
    assert "test-secret" not in serialized


async def test_disabled_thinking_mode_is_forwarded_to_compatible_router(
    tmp_path: Path,
) -> None:
    seen_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"content":"works"}'}}]},
        )

    generator = _generator(httpx.MockTransport(handler))
    generator.config = generator.config.model_copy(
        update={"thinking_mode": LlmThinkingMode.DISABLED}
    )
    _, orchestrator = await make_action(tmp_path, language_generator=generator)

    result = await orchestrator.process(
        make_event(
            event_id="openai-compatible-thinking-disabled",
            content="check this",
            mentions=("agent-001",),
        )
    )

    assert seen_payload["thinking"] == {"type": "disabled"}
    assert result.trace.status is CycleStatus.COMPLETED


async def test_empty_max_token_response_is_classified_as_output_truncated(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "max_tokens",
                        "message": {"content": ""},
                    }
                ]
            },
        )

    _, orchestrator = await make_action(
        tmp_path,
        language_generator=_generator(httpx.MockTransport(handler)),
    )
    result = await orchestrator.process(
        make_event(
            event_id="openai-compatible-output-truncated",
            content="check this",
            mentions=("agent-001",),
        )
    )

    assert result.trace.language_generation is not None
    assert result.trace.language_generation.error_code == "output_truncated"
    assert result.trace.language_generation.retryable is False
