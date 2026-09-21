from __future__ import annotations

import hmac
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from aelia.app.config import Settings, load_settings
from aelia.app.logging import get_logger
from aelia.backend.application import RuntimeApplication, RuntimeProtocolError
from aelia.contracts.adapter import AdapterInboundEnvelope
from aelia.contracts.connector import ExternalDeliveryReceipt
from aelia.contracts.runtime_api import (
    RuntimeErrorResponse,
    RuntimeHealthResponse,
    RuntimeIngressResponse,
    RuntimeReadyResponse,
    RuntimeReceiptResponse,
    RuntimeStatusResponse,
)
from aelia.storage.repositories import ConcurrentStateError

LOGGER = get_logger("backend.api")


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "runtime-request:unknown"))


def _error_response(
    request: Request,
    *,
    status_code: int,
    error: str,
    message: str,
) -> JSONResponse:
    payload = RuntimeErrorResponse(
        error=error,
        message=message,
        request_id=_request_id(request),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def _protocol_status(error: RuntimeProtocolError) -> int:
    return {
        "backend_not_ready": 503,
        "unknown_gate": 403,
        "gate_disabled": 403,
        "platform_mismatch": 403,
        "actor_not_allowed": 403,
        "conversation_not_allowed": 403,
        "receipt_rejected": 409,
    }.get(error.code, 400)


def create_app(
    settings: Settings | None = None,
    *,
    runtime: RuntimeApplication | None = None,
) -> FastAPI:
    resolved = settings or (runtime.settings if runtime is not None else load_settings())
    application = runtime or RuntimeApplication(resolved)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await application.initialize()
        try:
            yield
        finally:
            await application.shutdown()

    app = FastAPI(
        title="AELIA Runtime Backend",
        version=RuntimeApplication.API_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.runtime = application

    @app.middleware("http")
    async def protocol_boundaries(
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        supplied_id = request.headers.get("x-request-id", "").strip()
        request.state.request_id = (
            supplied_id if supplied_id and len(supplied_id) <= 256 else f"runtime-request:{uuid4()}"
        )
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                return _error_response(
                    request,
                    status_code=400,
                    error="invalid_content_length",
                    message="content-length must be an integer",
                )
            if declared_size > resolved.runtime_max_request_bytes:
                return _error_response(
                    request,
                    status_code=413,
                    error="request_too_large",
                    message="request body exceeds the configured limit",
                )
        if request.method in {"POST", "PUT", "PATCH"}:
            body = await request.body()
            if len(body) > resolved.runtime_max_request_bytes:
                return _error_response(
                    request,
                    status_code=413,
                    error="request_too_large",
                    message="request body exceeds the configured limit",
                )
        response = await call_next(request)
        response.headers["x-request-id"] = _request_id(request)
        response.headers["x-aelia-runtime-api-version"] = RuntimeApplication.API_VERSION
        return response

    async def authorize_gate(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> None:
        configured = resolved.runtime_gate_token
        if configured is None:
            return
        expected = f"Bearer {configured.get_secret_value()}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise RuntimeProtocolError("unauthorized", "missing or invalid runtime gate token")

    @app.exception_handler(RuntimeProtocolError)
    async def runtime_protocol_error(
        request: Request,
        error: RuntimeProtocolError,
    ) -> JSONResponse:
        status_code = 401 if error.code == "unauthorized" else _protocol_status(error)
        return _error_response(
            request,
            status_code=status_code,
            error=error.code,
            message=error.message,
        )

    @app.exception_handler(ConcurrentStateError)
    async def concurrent_state_error(
        request: Request,
        _: ConcurrentStateError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=409,
            error="concurrent_state_conflict",
            message="persona state changed before the ingress cycle could be committed",
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request,
        _: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            error="invalid_request",
            message="request does not match the runtime protocol schema",
        )

    @app.get("/health", response_model=RuntimeHealthResponse)
    async def health() -> RuntimeHealthResponse:
        return RuntimeHealthResponse.now()

    @app.get("/ready", response_model=RuntimeReadyResponse)
    async def ready() -> RuntimeReadyResponse:
        if application.ready:
            return RuntimeReadyResponse(ready=True, status="ready")
        return RuntimeReadyResponse(
            ready=False,
            status="failed" if application.startup_error else "starting",
            reason=application.startup_error,
        )

    @app.get(
        "/runtime/status",
        response_model=RuntimeStatusResponse,
        dependencies=[Depends(authorize_gate)],
    )
    async def runtime_status() -> RuntimeStatusResponse:
        return RuntimeStatusResponse.model_validate(application.status_payload())

    @app.post(
        "/v1/gates/ingress",
        response_model=RuntimeIngressResponse,
        dependencies=[Depends(authorize_gate)],
    )
    async def ingest(
        request: Request,
        envelope: AdapterInboundEnvelope,
    ) -> RuntimeIngressResponse:
        result = await application.ingest(envelope)
        LOGGER.info(
            "runtime_gate_ingress_processed",
            extra={
                "cycle_id": result.trace.cycle_id,
                "cycle_status": result.trace.status.value,
                "delivery_id": result.ingress.delivery_id,
                "dispatch_outcome": (
                    result.dispatch.decision.outcome.value
                    if result.dispatch is not None
                    else "none"
                ),
                "duplicate": result.ingress_duplicate,
                "event_id": result.trace.event_id,
            },
        )
        return RuntimeIngressResponse.from_result(
            request_id=_request_id(request),
            kernel_duplicate=result.kernel_duplicate,
            ingress_duplicate=result.ingress_duplicate,
            ingress=result.ingress,
            trace=result.trace,
            dispatch=result.dispatch,
        )

    @app.post(
        "/v1/gates/receipts",
        response_model=RuntimeReceiptResponse,
        dependencies=[Depends(authorize_gate)],
    )
    async def receipt(
        request: Request,
        external_receipt: ExternalDeliveryReceipt,
    ) -> RuntimeReceiptResponse:
        dispatch = await application.record_external_receipt(external_receipt)
        LOGGER.info(
            "runtime_gate_receipt_recorded",
            extra={
                "command_id": dispatch.command.command_id,
                "delivery_status": (
                    dispatch.receipt.status.value if dispatch.receipt is not None else "missing"
                ),
            },
        )
        return RuntimeReceiptResponse(request_id=_request_id(request), dispatch=dispatch)

    return app


__all__ = ["create_app"]
