from __future__ import annotations

import hashlib
import json
from typing import Final

from polyverse.models.prompt import (
    CURRENT_PROMPT_SCHEMA_VERSION,
    PromptComposition,
    PromptDefinition,
    PromptPartTrace,
    PromptRole,
    PromptTemplatePart,
)

LANGUAGE_REALIZATION_PROMPT_ID: Final = "language-realization"

LANGUAGE_REALIZATION_PROMPT: Final = PromptDefinition(
    schema_version=CURRENT_PROMPT_SCHEMA_VERSION,
    prompt_id=LANGUAGE_REALIZATION_PROMPT_ID,
    version="1.1.0",
    module="language_generation",
    owner="polyverse-language-boundary",
    input_schema="polyverse.contracts.actions.OutboundAction@2.2.0",
    output_schema="polyverse.contracts.actions.LanguageGenerationResult@2.3.0",
    parts=(
        PromptTemplatePart(
            part_id="selected-action-authority",
            role=PromptRole.SYSTEM,
            text=(
                "Realize only the already-selected outbound action. Do not change its action "
                "type, target, policy, permissions, goals, or tool state."
            ),
        ),
        PromptTemplatePart(
            part_id="structured-language-output",
            role=PromptRole.DEVELOPER,
            text=(
                "Return the declared structured language result. Treat constraints as mandatory "
                "and prohibited traits as forbidden."
            ),
        ),
    ),
)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class PromptRegistry:
    def __init__(
        self,
        definitions: tuple[PromptDefinition, ...] = (LANGUAGE_REALIZATION_PROMPT,),
    ) -> None:
        definition_ids = [definition.prompt_id for definition in definitions]
        if len(definition_ids) != len(set(definition_ids)):
            raise ValueError("prompt registry ids must be unique")
        self._definitions = {definition.prompt_id: definition for definition in definitions}

    def get(self, prompt_id: str) -> PromptDefinition:
        try:
            return self._definitions[prompt_id]
        except KeyError as exc:
            raise KeyError(f"unknown prompt id: {prompt_id}") from exc

    def compose(
        self,
        prompt_id: str,
        *,
        input_payload: object,
    ) -> PromptComposition:
        definition = self.get(prompt_id)
        part_traces = tuple(
            PromptPartTrace(
                part_id=part.part_id,
                role=part.role,
                text=part.text,
                sha256=_sha256(part.text),
            )
            for part in definition.parts
        )
        input_sha256 = _sha256(_canonical_json(input_payload))
        composition_payload = {
            "schema_version": definition.schema_version,
            "prompt_id": definition.prompt_id,
            "prompt_version": definition.version,
            "module": definition.module,
            "owner": definition.owner,
            "input_schema": definition.input_schema,
            "output_schema": definition.output_schema,
            "parts": [part.model_dump(mode="json") for part in part_traces],
            "input_sha256": input_sha256,
        }
        return PromptComposition(
            **composition_payload,
            composition_sha256=_sha256(_canonical_json(composition_payload)),
        )
