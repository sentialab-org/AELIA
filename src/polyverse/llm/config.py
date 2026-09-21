from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, SecretStr, field_validator

from polyverse.contracts.common import StrictModel


class LlmStructuredOutputMode(StrEnum):
    JSON_OBJECT = "json_object"
    JSON_SCHEMA = "json_schema"


class LlmThinkingMode(StrEnum):
    AUTO = "auto"
    ENABLED = "enabled"
    DISABLED = "disabled"


class OpenAICompatibleConfig(StrictModel):
    api_base: Annotated[str, Field(min_length=1, max_length=2048)]
    api_key: SecretStr
    model: Annotated[str, Field(min_length=1, max_length=256)]
    timeout_seconds: Annotated[float, Field(ge=1.0, le=300.0)]
    max_attempts: Annotated[int, Field(ge=1, le=5)]
    max_output_tokens: Annotated[int, Field(ge=32, le=16_384)]
    structured_output_mode: LlmStructuredOutputMode
    allow_plain_text_fallback: bool = False
    thinking_mode: LlmThinkingMode = LlmThinkingMode.AUTO

    @field_validator("api_base")
    @classmethod
    def normalize_api_base(cls, value: str) -> str:
        return value.rstrip("/")
