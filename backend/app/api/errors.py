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

from app.api.schemas import ApiErrorDetail, ApiErrorResponse
from app.config.loader import ConfigLoadError
from app.config.view import ApiSettings, ObservabilitySettings
from app.contracts.errors import (
    LLMGatewayError,
    PolicyDeniedError,
    ToolGatewayError,
    TraceStoreError,
    WorkflowStateError,
)
from app.observability.events import ERROR_OCCURRED
from app.observability.errors import build_log_error_details, build_trace_error_details
from app.observability.ids import new_trace_id
from app.observability.models import TRACE_ID_HEADER
from app.observability.redaction import Redactor
from app.observability.tracing import TraceRecorder
from app.session.errors import SessionConflictError, SessionNotFoundError, UnknownUseCaseError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiError(Exception):
    """Explicit API error for future route and service use."""

    code: str
    message: str
    status_code: int
    retryable: bool = False
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
            retryable=exc.retryable,
            details=exc.details,
        )
        return build_api_error_response(
            request=request,
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            retryable=exc.retryable,
            details=exc.details,
        )

    @app.exception_handler(ConfigLoadError)
    async def handle_config_error(request: Request, exc: ConfigLoadError) -> JSONResponse:
        await _emit_error_observability(
            request=request,
            exc=exc,
            code="config_load_error",
            status_code=500,
        )
        return build_api_error_response(
            request=request,
            code="config_load_error",
            message="Configuration could not be loaded.",
            status_code=500,
        )

    @app.exception_handler(SessionNotFoundError)
    async def handle_session_not_found(
        request: Request,
        exc: SessionNotFoundError,
    ) -> JSONResponse:
        await _emit_error_observability(
            request=request,
            exc=exc,
            code="session_not_found",
            status_code=404,
        )
        return build_api_error_response(
            request=request,
            code="session_not_found",
            message="The requested session was not found.",
            status_code=404,
        )

    @app.exception_handler(SessionConflictError)
    async def handle_session_conflict(
        request: Request,
        exc: SessionConflictError,
    ) -> JSONResponse:
        await _emit_error_observability(
            request=request,
            exc=exc,
            code="session_conflict",
            status_code=409,
        )
        return build_api_error_response(
            request=request,
            code="session_conflict",
            message="The session request conflicted with the current session state.",
            status_code=409,
        )

    @app.exception_handler(UnknownUseCaseError)
    async def handle_unknown_usecase(
        request: Request,
        exc: UnknownUseCaseError,
    ) -> JSONResponse:
        await _emit_error_observability(
            request=request,
            exc=exc,
            code="unknown_usecase",
            status_code=400,
        )
        return build_api_error_response(
            request=request,
            code="unknown_usecase",
            message="The requested use case is not available.",
            status_code=400,
        )

    @app.exception_handler(PolicyDeniedError)
    async def handle_policy_denied(
        request: Request,
        exc: PolicyDeniedError,
    ) -> JSONResponse:
        await _emit_error_observability(
            request=request,
            exc=exc,
            code="policy_denied",
            status_code=403,
        )
        return build_api_error_response(
            request=request,
            code="policy_denied",
            message="The requested action is not allowed.",
            status_code=403,
        )

    @app.exception_handler(WorkflowStateError)
    async def handle_workflow_state_error(
        request: Request,
        exc: WorkflowStateError,
    ) -> JSONResponse:
        await _emit_error_observability(
            request=request,
            exc=exc,
            code="workflow_state_unavailable",
            status_code=503,
            retryable=True,
        )
        return build_api_error_response(
            request=request,
            code="workflow_state_unavailable",
            message="Workflow state is temporarily unavailable.",
            status_code=503,
            retryable=True,
        )

    @app.exception_handler(TraceStoreError)
    async def handle_trace_store_error(
        request: Request,
        exc: TraceStoreError,
    ) -> JSONResponse:
        await _emit_error_observability(
            request=request,
            exc=exc,
            code="trace_store_unavailable",
            status_code=503,
            retryable=True,
        )
        return build_api_error_response(
            request=request,
            code="trace_store_unavailable",
            message="Trace recording is temporarily unavailable.",
            status_code=503,
            retryable=True,
        )

    @app.exception_handler(LLMGatewayError)
    async def handle_llm_gateway_error(
        request: Request,
        exc: LLMGatewayError,
    ) -> JSONResponse:
        await _emit_error_observability(
            request=request,
            exc=exc,
            code="llm_unavailable",
            status_code=503,
            retryable=True,
        )
        return build_api_error_response(
            request=request,
            code="llm_unavailable",
            message="The configured LLM provider is temporarily unavailable.",
            status_code=503,
            retryable=True,
        )

    @app.exception_handler(ToolGatewayError)
    async def handle_tool_gateway_error(
        request: Request,
        exc: ToolGatewayError,
    ) -> JSONResponse:
        await _emit_error_observability(
            request=request,
            exc=exc,
            code="tool_unavailable",
            status_code=503,
            retryable=True,
        )
        return build_api_error_response(
            request=request,
            code="tool_unavailable",
            message="The configured tool backend is temporarily unavailable.",
            status_code=503,
            retryable=True,
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
            code="validation_error",
            status_code=422,
            details={"errors": sanitized_errors},
        )
        return build_api_error_response(
            request=request,
            code="validation_error",
            message="The request is invalid.",
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
                code="not_found",
                status_code=404,
            )
            return build_api_error_response(
                request=request,
                code="not_found",
                message="Resource not found.",
                status_code=404,
            )

        await _emit_error_observability(
            request=request,
            exc=exc,
            code="internal_error",
            status_code=exc.status_code,
        )
        return build_api_error_response(
            request=request,
            code="internal_error",
            message="An internal server error occurred.",
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        await _emit_error_observability(
            request=request,
            exc=exc,
            code="internal_error",
            status_code=500,
        )
        return build_api_error_response(
            request=request,
            code="internal_error",
            message="An internal server error occurred.",
            status_code=500,
        )


def build_api_error_response(
    *,
    request: Request,
    code: str,
    message: str,
    status_code: int,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    trace_id = _resolve_response_trace_id(request)
    payload = ApiErrorResponse(
        trace_id=trace_id,
        error=ApiErrorDetail(
            code=code,
            message=message,
            retryable=retryable,
            details=details or {},
        ),
    )
    response = JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))
    response.headers[_get_trace_response_header_name(request)] = trace_id
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
    code: str,
    status_code: int,
    retryable: bool = False,
    details: Mapping[str, Any] | None = None,
) -> None:
    trace_recorder = _get_trace_recorder(request)
    redactor = _get_redactor(request)
    settings = _get_observability_settings(request)
    api_settings = _get_api_settings(request)
    route = _resolve_route(request)
    safe_details: dict[str, Any] = {
        "method": request.method,
        "route_template": route,
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

    if code == "validation_error" and api_settings is not None:
        if not api_settings.tracing.record_validation_errors:
            return

    if settings.trace_enabled is False:
        return

    await trace_recorder.record(
        event_type="error",
        event_name=ERROR_OCCURRED,
        component="api.errors",
        trace_id=getattr(request.state, "trace_id", None),
        status="failed",
        severity="error" if status_code >= 500 else "warning",
        error_type=type(exc).__name__,
        error_code=str(code),
        retryable=retryable,
        payload={
            **build_trace_error_details(
                exc,
                redactor=redactor,
                details=safe_details,
                include_stack_trace=include_stack_in_traces,
            ),
            "route_template": route,
        },
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


def _get_api_settings(request: Request) -> ApiSettings | None:
    container = getattr(request.app.state, "container", None)
    api_settings = getattr(container, "api_settings", None)
    if isinstance(api_settings, ApiSettings):
        return api_settings
    return None


def _resolve_response_trace_id(request: Request) -> str:
    trace_id = getattr(request.state, "trace_id", None)
    if isinstance(trace_id, str) and trace_id.strip():
        return trace_id

    generated = new_trace_id()
    request.state.trace_id = generated
    return generated


def _get_trace_response_header_name(request: Request) -> str:
    api_settings = _get_api_settings(request)
    if api_settings is None:
        return TRACE_ID_HEADER
    return api_settings.tracing.response_trace_header


def _resolve_route(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path
    return request.url.path