from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, cast

import httpx
from pydantic import Field, field_validator

from aelia.contracts.actions import (
    LanguageGenerationResult,
    LanguageGenerationStatus,
    OutboundAction,
)
from aelia.contracts.common import StrictModel
from aelia.contracts.events import InboundEvent
from aelia.llm.config import (
    LlmStructuredOutputMode,
    LlmThinkingMode,
    OpenAICompatibleConfig,
)
from aelia.persona.models import PersonaView

GENERATOR_ID = "openai-compatible-chat-completions-v1"
PROVIDER_ID = "openai_compatible"
MAX_RESPONSE_BYTES = 1_000_000


class LlmProviderProbe(StrictModel):
    provider: str
    api_base: str
    model: str
    reachable: bool
    model_listed: bool | None
    status_code: int | None
    request_id: str | None
    error_code: str | None


class LanguageRealizationPayload(StrictModel):
    content: Annotated[str, Field(min_length=1, max_length=10_000)]

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("language realization content must not be blank")
        return normalized


class _ProviderFailure(Exception):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        request_id: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.request_id = request_id
        self.retry_after_seconds = retry_after_seconds


Sleep = Callable[[float], Awaitable[None]]


class OpenAICompatibleLanguageGenerator:
    """Async Chat Completions client that can only realize a selected action."""

    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.config = config
        self.transport = transport
        self.sleep = sleep

    async def generate(
        self,
        action: OutboundAction,
        *,
        event: InboundEvent,
        persona_view: PersonaView,
    ) -> LanguageGenerationResult:
        last_failure: _ProviderFailure | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                content, request_id = await self._request(
                    action=action,
                    event=event,
                    persona_view=persona_view,
                )
            except _ProviderFailure as failure:
                last_failure = failure
                if not failure.retryable or attempt >= self.config.max_attempts:
                    return self._failed_result(
                        action=action,
                        attempts=attempt,
                        failure=failure,
                    )
                default_delay = (
                    1.0 * (2 ** (attempt - 1))
                    if failure.code == "http_429"
                    else 0.5 * (2 ** (attempt - 1))
                )
                delay = max(default_delay, failure.retry_after_seconds or 0.0)
                await self.sleep(min(delay, 30.0))
                continue
            return LanguageGenerationResult(
                action_id=action.action_id,
                generator=GENERATOR_ID,
                status=LanguageGenerationStatus.GENERATED,
                content=content,
                selected_action_type=action.action_type,
                applied_constraints=action.content_plan.constraints,
                changed_participation=False,
                provider=PROVIDER_ID,
                model=self.config.model,
                request_id=request_id,
                attempts=attempt,
            )
        if last_failure is None:
            raise RuntimeError("LLM generation exhausted attempts without a result")
        return self._failed_result(
            action=action,
            attempts=self.config.max_attempts,
            failure=last_failure,
        )

    async def probe(self) -> LlmProviderProbe:
        endpoint = f"{self.config.api_base}/models"
        try:
            async with self._client() as client:
                response = await client.get(endpoint)
        except httpx.TimeoutException:
            return self._probe_failure("timeout")
        except httpx.RequestError:
            return self._probe_failure("network_error")

        request_id = self._request_id(response)
        if not response.is_success:
            return LlmProviderProbe(
                provider=PROVIDER_ID,
                api_base=self.config.api_base,
                model=self.config.model,
                reachable=False,
                model_listed=None,
                status_code=response.status_code,
                request_id=request_id,
                error_code=f"http_{response.status_code}",
            )
        model_listed: bool | None = None
        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            model_ids = {
                item.get("id")
                for item in payload["data"]
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            model_listed = self.config.model in model_ids
        return LlmProviderProbe(
            provider=PROVIDER_ID,
            api_base=self.config.api_base,
            model=self.config.model,
            reachable=True,
            model_listed=model_listed,
            status_code=response.status_code,
            request_id=request_id,
            error_code=None,
        )

    async def _request(
        self,
        *,
        action: OutboundAction,
        event: InboundEvent,
        persona_view: PersonaView,
    ) -> tuple[str, str | None]:
        try:
            async with self._client() as client:
                response = await client.post(
                    f"{self.config.api_base}/chat/completions",
                    json=self._request_payload(
                        action=action,
                        event=event,
                        persona_view=persona_view,
                    ),
                )
        except (httpx.ConnectTimeout, httpx.ConnectError) as exc:
            raise _ProviderFailure("connect_error", retryable=True) from exc
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise _ProviderFailure(
                "ambiguous_transport_failure",
                retryable=False,
            ) from exc

        request_id = self._request_id(response)
        if not response.is_success:
            retryable = response.status_code in {408, 409, 429} or response.status_code >= 500
            raise _ProviderFailure(
                f"http_{response.status_code}",
                retryable=retryable,
                request_id=request_id,
                retry_after_seconds=self._retry_after_seconds(response),
            )
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise _ProviderFailure(
                "response_too_large",
                retryable=False,
                request_id=request_id,
            )
        try:
            response_payload: Any = response.json()
        except json.JSONDecodeError as exc:
            raise _ProviderFailure(
                "invalid_response_json",
                retryable=False,
                request_id=request_id,
            ) from exc
        message = self._first_message(response_payload, request_id=request_id)
        refusal = message.get("refusal")
        if isinstance(refusal, str) and refusal.strip():
            raise _ProviderFailure(
                "model_refusal",
                retryable=False,
                request_id=request_id,
            )
        raw_content = message.get("content")
        if not isinstance(raw_content, str):
            raise _ProviderFailure(
                "missing_message_content",
                retryable=False,
                request_id=request_id,
            )
        if not raw_content.strip():
            finish_reason = self._finish_reason(response_payload)
            raise _ProviderFailure(
                "output_truncated" if finish_reason == "max_tokens" else "empty_message_content",
                retryable=False,
                request_id=request_id,
            )
        try:
            structured_content = self._decode_structured_content(raw_content)
            realized = LanguageRealizationPayload.model_validate(structured_content)
        except (json.JSONDecodeError, ValueError) as exc:
            if self.config.allow_plain_text_fallback:
                fallback = self._plain_text_fallback(raw_content)
                if fallback is not None:
                    return fallback, request_id
            raise _ProviderFailure(
                "invalid_structured_output",
                retryable=False,
                request_id=request_id,
            ) from exc
        return realized.content, request_id

    @staticmethod
    def _plain_text_fallback(raw_content: str) -> str | None:
        normalized = raw_content.strip()
        if not normalized or normalized.startswith(("{", "[")):
            return None
        try:
            return LanguageRealizationPayload(content=normalized).content
        except ValueError:
            return None

    @staticmethod
    def _decode_structured_content(raw_content: str) -> Any:
        normalized = raw_content.strip()
        if normalized.startswith("```") and normalized.endswith("```"):
            lines = normalized.splitlines()
            if len(lines) < 3 or lines[0].casefold() not in {"```", "```json"}:
                raise ValueError("unsupported structured-output code fence")
            normalized = "\n".join(lines[1:-1]).strip()
        return json.loads(normalized)

    def _request_payload(
        self,
        *,
        action: OutboundAction,
        event: InboundEvent,
        persona_view: PersonaView,
    ) -> dict[str, Any]:
        prompt = action.content_plan.prompt
        if prompt is None:
            raise ValueError("OpenAI-compatible generation requires prompt metadata")
        messages = [
            {
                "role": part.role.value,
                "content": part.text,
            }
            for part in prompt.parts
        ]
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "Realize the selected action as natural dialogue.",
                        "source_message": event.content,
                        "intent": action.content_plan.intent,
                        "constraints": action.content_plan.constraints,
                        "prohibited_traits": action.content_plan.prohibited_traits,
                        "persona": {
                            "language": persona_view.language.value,
                            "relationship_tier": persona_view.relationship_tier.value,
                            "rules": [
                                {
                                    "rule_id": rule.rule_id,
                                    "category": rule.category,
                                    "instruction": rule.instruction,
                                }
                                for rule in persona_view.all_rules()
                            ],
                        },
                        "required_output": {
                            "content": "The dialogue text only, without meta commentary."
                        },
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            }
        )
        payload = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_output_tokens,
            "stream": False,
            "response_format": self._response_format(),
        }
        if self.config.thinking_mode is not LlmThinkingMode.AUTO:
            payload["thinking"] = {"type": self.config.thinking_mode.value}
        return payload

    def _response_format(self) -> dict[str, Any]:
        if self.config.structured_output_mode is LlmStructuredOutputMode.JSON_SCHEMA:
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": "aelia_language_realization",
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
        return {"type": "json_object"}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.config.api_key.get_secret_value()}",
                "Content-Type": "application/json",
                "User-Agent": "aelia/0.1.0",
            },
            timeout=httpx.Timeout(self.config.timeout_seconds),
            follow_redirects=False,
            transport=self.transport,
        )

    def _failed_result(
        self,
        *,
        action: OutboundAction,
        attempts: int,
        failure: _ProviderFailure,
    ) -> LanguageGenerationResult:
        return LanguageGenerationResult(
            action_id=action.action_id,
            generator=GENERATOR_ID,
            status=LanguageGenerationStatus.FAILED,
            content=None,
            selected_action_type=action.action_type,
            applied_constraints=action.content_plan.constraints,
            changed_participation=False,
            provider=PROVIDER_ID,
            model=self.config.model,
            request_id=failure.request_id,
            attempts=attempts,
            error_code=failure.code,
            retryable=failure.retryable,
        )

    def _probe_failure(self, error_code: str) -> LlmProviderProbe:
        return LlmProviderProbe(
            provider=PROVIDER_ID,
            api_base=self.config.api_base,
            model=self.config.model,
            reachable=False,
            model_listed=None,
            status_code=None,
            request_id=None,
            error_code=error_code,
        )

    @staticmethod
    def _first_message(
        payload: Any,
        *,
        request_id: str | None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise _ProviderFailure(
                "invalid_response_shape",
                retryable=False,
                request_id=request_id,
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise _ProviderFailure(
                "invalid_response_shape",
                retryable=False,
                request_id=request_id,
            )
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise _ProviderFailure(
                "invalid_response_shape",
                retryable=False,
                request_id=request_id,
            )
        return message

    @staticmethod
    def _finish_reason(payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return None
        value = choices[0].get("finish_reason")
        return value if isinstance(value, str) else None

    @staticmethod
    def _request_id(response: httpx.Response) -> str | None:
        return cast(
            str | None,
            response.headers.get("x-request-id") or response.headers.get("openai-request-id"),
        )

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        raw = response.headers.get("retry-after")
        if raw is None:
            return None
        try:
            parsed = float(raw)
        except ValueError:
            return None
        return parsed if 0.0 <= parsed <= 300.0 else None
