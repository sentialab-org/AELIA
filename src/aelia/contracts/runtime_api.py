from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field

from aelia.contracts.adapter import AdapterDispatchRecord, AdapterIngressRecord
from aelia.contracts.common import NonEmptyId, StrictModel
from aelia.contracts.traces import CycleTrace

RUNTIME_API_VERSION: Literal["1.0.0"] = "1.0.0"


class RuntimeHealthResponse(StrictModel):
    api_version: Literal["1.0.0"] = RUNTIME_API_VERSION
    status: Literal["ok"] = "ok"
    service: Literal["aelia-runtime-backend"] = "aelia-runtime-backend"
    timestamp: datetime

    @classmethod
    def now(cls) -> RuntimeHealthResponse:
        return cls(timestamp=datetime.now(UTC))


class RuntimeReadyResponse(StrictModel):
    api_version: Literal["1.0.0"] = RUNTIME_API_VERSION
    ready: bool
    status: Literal["ready", "starting", "failed"]
    reason: str | None = None


class RuntimeStatusResponse(StrictModel):
    api_version: Literal["1.0.0"] = RUNTIME_API_VERSION
    service: Literal["aelia-runtime-backend"] = "aelia-runtime-backend"
    ready: bool
    environment: str
    agent_actor_id: NonEmptyId
    configured_gates: tuple[NonEmptyId, ...]
    llm_provider: str
    llm_model: str | None
    database_path: str


class RuntimeIngressResponse(StrictModel):
    api_version: Literal["1.0.0"] = RUNTIME_API_VERSION
    request_id: NonEmptyId
    kernel_duplicate: bool
    ingress_duplicate: bool
    ingress: AdapterIngressRecord
    trace: CycleTrace
    dispatch: AdapterDispatchRecord | None

    @classmethod
    def from_result(
        cls,
        *,
        request_id: str,
        kernel_duplicate: bool,
        ingress_duplicate: bool,
        ingress: AdapterIngressRecord,
        trace: CycleTrace,
        dispatch: AdapterDispatchRecord | None,
    ) -> RuntimeIngressResponse:
        return cls(
            request_id=request_id,
            kernel_duplicate=kernel_duplicate,
            ingress_duplicate=ingress_duplicate,
            ingress=ingress,
            trace=trace,
            dispatch=dispatch,
        )


class RuntimeReceiptResponse(StrictModel):
    api_version: Literal["1.0.0"] = RUNTIME_API_VERSION
    request_id: NonEmptyId
    dispatch: AdapterDispatchRecord


class RuntimeErrorResponse(StrictModel):
    api_version: Literal["1.0.0"] = RUNTIME_API_VERSION
    error: Annotated[str, Field(min_length=1, max_length=128)]
    message: Annotated[str, Field(min_length=1, max_length=2_048)]
    request_id: NonEmptyId


__all__ = [
    "RUNTIME_API_VERSION",
    "RuntimeErrorResponse",
    "RuntimeHealthResponse",
    "RuntimeIngressResponse",
    "RuntimeReadyResponse",
    "RuntimeReceiptResponse",
    "RuntimeStatusResponse",
]
