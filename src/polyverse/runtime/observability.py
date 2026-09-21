from __future__ import annotations

import hashlib
from typing import Any, Literal

from polyverse.contracts.common import StrictModel
from polyverse.storage.repositories import KernelRepository, canonical_json, sha256_text

TRACE_EXPORT_SCHEMA_VERSION = "1.0.0"

_SENSITIVE_TEXT_KEYS = frozenset(
    {
        "constraints",
        "content",
        "description",
        "error_message",
        "filename",
        "statement",
        "source_url",
        "value",
    }
)


class TraceComparison(StrictModel):
    left_cycle_id: str
    right_cycle_id: str
    same_event: bool
    exact_match: bool
    left_sha256: str
    right_sha256: str
    differing_paths: tuple[str, ...]
    differences_truncated: bool


class TraceExportPackage(StrictModel):
    export_schema_version: Literal["1.0.0"]
    private_data_redacted: bool
    event_sha256: str
    trace_sha256: str
    event: dict[str, Any]
    trace: dict[str, Any]


class TraceObservabilityService:
    def __init__(self, repository: KernelRepository) -> None:
        self.repository = repository

    async def compare_cycles(
        self,
        left_cycle_id: str,
        right_cycle_id: str,
        *,
        max_differences: int = 200,
    ) -> TraceComparison:
        if max_differences < 1:
            raise ValueError("max_differences must be positive")
        left = await self.repository.get_cycle(left_cycle_id)
        right = await self.repository.get_cycle(right_cycle_id)
        left_payload = left.model_dump(mode="json")
        right_payload = right.model_dump(mode="json")
        differences: list[str] = []
        truncated = self._collect_differences(
            left_payload,
            right_payload,
            path="$",
            differences=differences,
            limit=max_differences,
        )
        left_json = canonical_json(left_payload)
        right_json = canonical_json(right_payload)
        return TraceComparison(
            left_cycle_id=left_cycle_id,
            right_cycle_id=right_cycle_id,
            same_event=left.event_id == right.event_id,
            exact_match=left_json == right_json,
            left_sha256=sha256_text(left_json),
            right_sha256=sha256_text(right_json),
            differing_paths=tuple(differences),
            differences_truncated=truncated,
        )

    async def export_cycle(
        self,
        cycle_id: str,
        *,
        redact_private_data: bool = True,
    ) -> TraceExportPackage:
        trace = await self.repository.get_cycle(cycle_id)
        event = await self.repository.get_event(trace.event_id)
        event_payload = event.model_dump(mode="json")
        trace_payload = trace.model_dump(mode="json")
        exported_event = self._redact(event_payload) if redact_private_data else event_payload
        exported_trace = self._redact(trace_payload) if redact_private_data else trace_payload
        return TraceExportPackage(
            export_schema_version=TRACE_EXPORT_SCHEMA_VERSION,
            private_data_redacted=redact_private_data,
            event_sha256=sha256_text(canonical_json(event_payload)),
            trace_sha256=sha256_text(canonical_json(trace_payload)),
            event=exported_event,
            trace=exported_trace,
        )

    @classmethod
    def _redact(cls, value: Any, *, key: str | None = None) -> Any:
        if key in _SENSITIVE_TEXT_KEYS:
            return "[REDACTED]"
        if key is not None and key.endswith("_id") and value is not None:
            return cls._pseudonym(str(value))
        if key is not None and key.endswith("_ids") and isinstance(value, list):
            return [cls._pseudonym(str(item)) for item in value]
        if isinstance(value, dict):
            return {
                str(child_key): cls._redact(child_value, key=str(child_key))
                for child_key, child_value in value.items()
            }
        if isinstance(value, list):
            return [cls._redact(item) for item in value]
        return value

    @staticmethod
    def _pseudonym(value: str) -> str:
        digest = hashlib.sha256(value.encode()).hexdigest()[:16]
        return f"redacted:{digest}"

    @classmethod
    def _collect_differences(
        cls,
        left: Any,
        right: Any,
        *,
        path: str,
        differences: list[str],
        limit: int,
    ) -> bool:
        if len(differences) >= limit:
            return True
        if type(left) is not type(right):
            differences.append(path)
            return len(differences) >= limit
        if isinstance(left, dict):
            truncated = False
            for key in sorted(set(left) | set(right)):
                child_path = f"{path}.{key}"
                if key not in left or key not in right:
                    differences.append(child_path)
                else:
                    truncated = cls._collect_differences(
                        left[key],
                        right[key],
                        path=child_path,
                        differences=differences,
                        limit=limit,
                    )
                if len(differences) >= limit:
                    return True
            return truncated
        if isinstance(left, list):
            truncated = False
            if len(left) != len(right):
                differences.append(f"{path}.length")
                if len(differences) >= limit:
                    return True
            for index, (left_item, right_item) in enumerate(zip(left, right, strict=False)):
                truncated = cls._collect_differences(
                    left_item,
                    right_item,
                    path=f"{path}[{index}]",
                    differences=differences,
                    limit=limit,
                )
                if len(differences) >= limit:
                    return True
            return truncated
        if left != right:
            differences.append(path)
        return len(differences) >= limit
