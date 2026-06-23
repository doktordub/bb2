"""Foundation API error handlers."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config.loader import ConfigLoadError
from app.config.view import ObservabilitySettings
from app.observability.events import ERROR_OCCURRED
from app.observability.errors import build_log_error_details, build_trace_error_details
from app.observability.models import ApiErrorEnvelope, ApiErrorModel, ErrorCode, TRACE_ID_HEADER
from app.observability.redaction import Redactor
from app.observability.tracing import TraceRecorder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiError(Exception):
    """Explicit API error for future route and service use."""

    code: ErrorCode
    message: str
    status_code: int
    details: dict[str, Any] = field(default_factory=dict)


def register_exception_handlers(app: FastAPI) -> None:
    """Register foundation exception handlers on the FastAPI app."""

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        await _emit_error_observability(
            request=request,
            exc=exc,
            code=exc.code,
            status_code=exc.status_code,
            details=exc.details,
        )
        return _build_error_response(
            request=request,
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=exc.details,
        )

    @app.exception_handler(ConfigLoadError)
    async def handle_config_error(request: Request, exc: ConfigLoadError) -> JSONResponse:
        await _emit_error_observability(
            request=request,
            exc=exc,
            code="CONFIG_LOAD_ERROR",
            status_code=500,
        )
        return _build_error_response(
            request=request,
            code="CONFIG_LOAD_ERROR",
            message="Configuration could not be loaded.",
            status_code=500,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        sanitized_errors = _sanitize_validation_errors(exc)
        await _emit_error_observability(
            request=request,
            exc=exc,
            code="VALIDATION_ERROR",
            status_code=422,
            details={"errors": sanitized_errors},
        )
        return _build_error_response(
            request=request,
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            status_code=422,
            details={"errors": sanitized_errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        if exc.status_code == 404:
            await _emit_error_observability(
                request=request,
                exc=exc,
                code="NOT_FOUND",
                status_code=404,
            )
            return _build_error_response(
                request=request,
                code="NOT_FOUND",
                message="Resource not found.",
                status_code=404,
            )

        await _emit_error_observability(
            request=request,
            exc=exc,
            code="INTERNAL_ERROR",
            status_code=exc.status_code,
        )
        return _build_error_response(
            request=request,
            code="INTERNAL_ERROR",
            message="An internal server error occurred.",
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        await _emit_error_observability(
            request=request,
            exc=exc,
            code="INTERNAL_ERROR",
            status_code=500,
        )
        return _build_error_response(
            request=request,
            code="INTERNAL_ERROR",
            message="An internal server error occurred.",
            status_code=500,
        )


def _build_error_response(
    *,
    request: Request,
    code: ErrorCode,
    message: str,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None)
    payload = ApiErrorEnvelope(
        error=ApiErrorModel(
            code=code,
            message=message,
            trace_id=trace_id,
            details=details or {},
        )
    )
    response = JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))
    if trace_id is not None:
        response.headers[TRACE_ID_HEADER] = trace_id
    return response


def _sanitize_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    sanitized_errors: list[dict[str, Any]] = []
    for error in exc.errors():
        sanitized_errors.append(
            {
                "loc": list(error.get("loc", [])),
                "msg": str(error.get("msg", "Invalid request.")),
                "type": str(error.get("type", "validation_error")),
            }
        )
    return sanitized_errors


async def _emit_error_observability(
    *,
    request: Request,
    exc: Exception,
    code: ErrorCode,
    status_code: int,
    details: Mapping[str, Any] | None = None,
) -> None:
    trace_recorder = _get_trace_recorder(request)
    redactor = _get_redactor(request)
    settings = _get_observability_settings(request)
    route = _resolve_route(request)
    safe_details: dict[str, Any] = {
        "method": request.method,
        "route": route,
        "status_code": status_code,
        "error_code": code,
    }
    if details:
        safe_details["response_details"] = dict(details)

    include_stack_in_logs = status_code >= 500 and settings.include_stack_traces_in_logs
    include_stack_in_traces = status_code >= 500 and settings.include_stack_traces_in_traces
    log_details = build_log_error_details(
        exc,
        redactor=redactor,
        details=safe_details,
        include_stack_trace=include_stack_in_logs,
    )
    logger.log(
        logging.ERROR if status_code >= 500 else logging.WARNING,
        "Request failed",
        extra={
            "component": "api.errors",
            "event_type": ERROR_OCCURRED,
            "status": "error",
            **log_details,
        },
        exc_info=(type(exc), exc, exc.__traceback__) if include_stack_in_logs else None,
    )

    if trace_recorder is None:
        return

    await trace_recorder.record(
        event_type=ERROR_OCCURRED,
        component="api.errors",
        trace_id=getattr(request.state, "trace_id", None),
        payload=build_trace_error_details(
            exc,
            redactor=redactor,
            details=safe_details,
            include_stack_trace=include_stack_in_traces,
        ),
    )


def _get_trace_recorder(request: Request) -> TraceRecorder | None:
    container = getattr(request.app.state, "container", None)
    trace_recorder = getattr(container, "trace_recorder", None)
    if isinstance(trace_recorder, TraceRecorder):
        return trace_recorder
    return None


def _get_redactor(request: Request) -> Redactor:
    container = getattr(request.app.state, "container", None)
    redactor = getattr(container, "redactor", None)
    if isinstance(redactor, Redactor):
        return redactor
    return Redactor(redact_secrets=True, max_chars=None)


def _get_observability_settings(request: Request) -> ObservabilitySettings:
    trace_recorder = _get_trace_recorder(request)
    if trace_recorder is not None:
        return trace_recorder.settings
    return ObservabilitySettings(
        log_level="INFO",
        structured_logging=True,
        trace_enabled=True,
        trace_payloads_enabled=True,
        trace_store_required=True,
        redact_secrets=True,
        include_stack_traces_in_logs=False,
        include_stack_traces_in_traces=False,
        max_trace_payload_chars=8000,
        slow_request_ms=5000,
        slow_llm_call_ms=30000,
        slow_tool_call_ms=10000,
        metrics_enabled=True,
    )


def _resolve_route(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path
    return request.url.path