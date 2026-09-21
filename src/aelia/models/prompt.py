from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from aelia.contracts.common import NonEmptyId, StrictModel

PromptSchemaVersion = Literal["1.0.0"]
CURRENT_PROMPT_SCHEMA_VERSION: PromptSchemaVersion = "1.0.0"


class PromptRole(StrEnum):
    SYSTEM = "system"
    DEVELOPER = "developer"


class PromptTemplatePart(StrictModel):
    part_id: NonEmptyId
    role: PromptRole
    text: Annotated[str, Field(min_length=1, max_length=4096)]


class PromptDefinition(StrictModel):
    schema_version: PromptSchemaVersion
    prompt_id: NonEmptyId
    version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    module: Annotated[str, Field(min_length=1, max_length=128)]
    owner: Annotated[str, Field(min_length=1, max_length=128)]
    input_schema: Annotated[str, Field(min_length=1, max_length=256)]
    output_schema: Annotated[str, Field(min_length=1, max_length=256)]
    parts: Annotated[tuple[PromptTemplatePart, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def require_unique_parts(self) -> PromptDefinition:
        part_ids = [part.part_id for part in self.parts]
        if len(part_ids) != len(set(part_ids)):
            raise ValueError("prompt definition part ids must be unique")
        return self


class PromptPartTrace(StrictModel):
    part_id: NonEmptyId
    role: PromptRole
    text: Annotated[str, Field(min_length=1, max_length=4096)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def validate_hash(self) -> PromptPartTrace:
        expected = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.sha256 != expected:
            raise ValueError("prompt part sha256 does not match its text")
        return self


class PromptComposition(StrictModel):
    schema_version: PromptSchemaVersion
    prompt_id: NonEmptyId
    prompt_version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    module: Annotated[str, Field(min_length=1, max_length=128)]
    owner: Annotated[str, Field(min_length=1, max_length=128)]
    input_schema: Annotated[str, Field(min_length=1, max_length=256)]
    output_schema: Annotated[str, Field(min_length=1, max_length=256)]
    parts: Annotated[tuple[PromptPartTrace, ...], Field(min_length=1)]
    input_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    composition_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
