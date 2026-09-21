from __future__ import annotations

import hashlib
import json

import pytest

from polyverse.llm.prompts import (
    LANGUAGE_REALIZATION_PROMPT,
    LANGUAGE_REALIZATION_PROMPT_ID,
    PromptRegistry,
)


def test_language_prompt_definition_has_a_stable_reviewable_snapshot() -> None:
    payload = json.dumps(
        LANGUAGE_REALIZATION_PROMPT.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert LANGUAGE_REALIZATION_PROMPT.schema_version == "1.0.0"
    assert LANGUAGE_REALIZATION_PROMPT.version == "1.1.0"
    assert LANGUAGE_REALIZATION_PROMPT.owner == "polyverse-language-boundary"
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == (
        "1d17e6b04cccf3cfd06a05c5e4da769359a33d9310c8dfa68a2efff6d8b6d87a"
    )


def test_prompt_composition_traces_parts_and_hashes_dynamic_input() -> None:
    registry = PromptRegistry()
    first = registry.compose(
        LANGUAGE_REALIZATION_PROMPT_ID,
        input_payload={"intent": "reply", "constraints": ["brief"]},
    )
    repeated = registry.compose(
        LANGUAGE_REALIZATION_PROMPT_ID,
        input_payload={"intent": "reply", "constraints": ["brief"]},
    )
    changed = registry.compose(
        LANGUAGE_REALIZATION_PROMPT_ID,
        input_payload={"intent": "join", "constraints": ["brief"]},
    )

    assert first == repeated
    assert first.input_sha256 != changed.input_sha256
    assert first.composition_sha256 != changed.composition_sha256
    assert tuple(part.part_id for part in first.parts) == (
        "selected-action-authority",
        "structured-language-output",
    )
    assert all(part.sha256 for part in first.parts)


def test_prompt_registry_rejects_unknown_and_duplicate_ids() -> None:
    registry = PromptRegistry()

    with pytest.raises(KeyError, match="unknown prompt id"):
        registry.get("missing")
    with pytest.raises(ValueError, match="ids must be unique"):
        PromptRegistry((LANGUAGE_REALIZATION_PROMPT, LANGUAGE_REALIZATION_PROMPT))
