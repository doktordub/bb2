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
    MCPAuthenticationError,
    MCPDiscoveryError,
    MCPTransportError,
    MemoryAdapterError,
    MemoryDisabledError,
    MemoryGatewayError,
    MemoryIngestionError,
    MemoryInvalidScopeError,
    MemoryNotFoundError,
    MemoryPolicyApprovalRequiredError,
    MemoryPrivacyError,
    PolicyApprovalRequiredError,
    PolicyDeniedError,
    ToolArgumentValidationError,
    ToolCancelledError,
    ToolDisabledError,
    ToolGatewayError,
    ToolNotFoundError,
    ToolPolicyApprovalRequiredError,
    ToolPolicyDeniedError,
    ToolResultTooLargeError,
    ToolTimeoutError,
    TraceStoreError,
    WorkflowStateError,
)
from app.llm.errors import (
    LLMBadRequestError,
    LLMAuthenticationError,
    LLMCancelledError,
    LLMContextLengthError,
    LLMMalformedResponseError,
    LLMPolicyDeniedError,
    LLMProfileResolutionError,
    LLMProviderTimeoutError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMRuntimeError,
    LLMStreamingError,
    LLMUnsupportedCapabilityError,
)
from app.observability.events import ERROR_OCCURRED
from app.observability.errors import build_log_error_details, build_trace_error_details
from app.observability.ids import new_trace_id
from app.observability.models import TRACE_ID_HEADER
from app.observability.redaction import Redactor
from app.observability.tracing import TraceRecorder
from app.session.errors import (
    InvalidSessionIdError,
    SessionConflictError,
    SessionDeleteDisabledError,
    SessionDeleteFailedError,
    SessionError,
    SessionHistoryDisabledError,
    SessionHistoryUnavailableError,
    SessionIdRequiredError,
    SessionListDisabledError,
    SessionListUnavailableError,
    SessionNotFoundError,
    SessionResetFailedError,
    SessionStateUnavailableError,
    UnknownUseCaseError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiError(Exception):
    """Explicit API error for future route and service use."""

    code: str
    message: str
    status_code: int
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _MappedApiError:
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

    @app.exception_handler(SessionError)
    async def handle_session_error(
        request: Request,
        exc: SessionError,
    ) -> JSONResponse:
        status_code = _session_error_status(exc)
        await _emit_error_observability(
            request=request,
            exc=exc,
            code=exc.code,
            status_code=status_code,
            retryable=exc.retryable,
            details=exc.details,
        )
        return build_api_error_response(
            request=request,
            code=exc.code,
            message=exc.message,
            status_code=status_code,
            retryable=exc.retryable,
            details=exc.details,
        )

    @app.exception_handler(PolicyDeniedError)
    async def handle_policy_denied(
        request: Request,
        exc: PolicyDeniedError,
    ) -> JSONResponse:
        if isinstance(exc, PolicyApprovalRequiredError):
            await _emit_error_observability(
                request=request,
                exc=exc,
                code="policy_approval_required",
                status_code=403,
            )
            return build_api_error_response(
                request=request,
                code="policy_approval_required",
                message="The requested action requires approval.",
                status_code=403,
            )
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

    @app.exception_handler(MemoryGatewayError)
    async def handle_memory_gateway_error(
        request: Request,
        exc: MemoryGatewayError,
    ) -> JSONResponse:
        mapped = _map_memory_error(exc)
        await _emit_error_observability(
            request=request,
            exc=exc,
            code=mapped.code,
            status_code=mapped.status_code,
            retryable=mapped.retryable,
            details=mapped.details,
        )
        return build_api_error_response(
            request=request,
            code=mapped.code,
            message=mapped.message,
            status_code=mapped.status_code,
            retryable=mapped.retryable,
            details=mapped.details,
        )

    @app.exception_handler(LLMRuntimeError)
    async def handle_llm_runtime_error(
        request: Request,
        exc: LLMRuntimeError,
    ) -> JSONResponse:
        mapped = _map_llm_runtime_error(exc)
        await _emit_error_observability(
            request=request,
            exc=exc,
            code=mapped.code,
            status_code=mapped.status_code,
            retryable=mapped.retryable,
            details=mapped.details,
        )
        return build_api_error_response(
            request=request,
            code=mapped.code,
            message=mapped.message,
            status_code=mapped.status_code,
            retryable=mapped.retryable,
            details=mapped.details,
        )

    @app.exception_handler(ToolGatewayError)
    async def handle_tool_gateway_error(
        request: Request,
        exc: ToolGatewayError,
    ) -> JSONResponse:
        mapped = _map_tool_error(exc)
        await _emit_error_observability(
            request=request,
            exc=exc,
            code=mapped.code,
            status_code=mapped.status_code,
            retryable=mapped.retryable,
            details=mapped.details,
        )
        return build_api_error_response(
            request=request,
            code=mapped.code,
            message=mapped.message,
            status_code=mapped.status_code,
            retryable=mapped.retryable,
            details=mapped.details,
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


def _session_error_status(exc: SessionError) -> int:
    if isinstance(exc, InvalidSessionIdError | SessionIdRequiredError | UnknownUseCaseError):
        return 400
    if isinstance(exc, SessionNotFoundError):
        return 404
    if isinstance(exc, SessionConflictError):
        return 409
    if isinstance(exc, SessionHistoryDisabledError | SessionListDisabledError | SessionDeleteDisabledError):
        return 404
    if isinstance(
        exc,
        (
            SessionStateUnavailableError
            | SessionResetFailedError
            | SessionHistoryUnavailableError
            | SessionListUnavailableError
            | SessionDeleteFailedError
        ),
    ):
        return 503
    return 500


def _map_llm_runtime_error(exc: LLMRuntimeError) -> _MappedApiError:
    if isinstance(exc, LLMPolicyDeniedError):
        return _MappedApiError(
            code="policy_denied",
            message="The requested LLM action is not allowed.",
            status_code=403,
            retryable=exc.retryable,
        )
    if isinstance(exc, LLMProfileResolutionError):
        return _MappedApiError(
            code="unknown_llm_profile",
            message="The requested LLM profile is not available.",
            status_code=400,
            retryable=exc.retryable,
        )
    if isinstance(exc, LLMUnsupportedCapabilityError):
        return _MappedApiError(
            code="unsupported_llm_capability",
            message="The requested LLM capability is not supported.",
            status_code=400,
            retryable=exc.retryable,
        )
    if isinstance(exc, LLMContextLengthError):
        return _MappedApiError(
            code="context_too_large",
            message="The request exceeds the configured LLM context limit.",
            status_code=400,
            retryable=exc.retryable,
        )
    if isinstance(exc, LLMProviderTimeoutError):
        return _MappedApiError(
            code="llm_timeout",
            message="The configured LLM provider timed out.",
            status_code=504,
            retryable=exc.retryable,
        )
    if isinstance(exc, LLMRateLimitError):
        return _MappedApiError(
            code="llm_rate_limited",
            message="The configured LLM provider is temporarily rate limited.",
            status_code=503,
            retryable=exc.retryable,
        )
    if isinstance(exc, LLMAuthenticationError):
        return _MappedApiError(
            code="llm_authentication_failed",
            message="The configured LLM provider could not be authenticated.",
            status_code=503,
            retryable=exc.retryable,
        )
    if isinstance(exc, LLMBadRequestError):
        return _MappedApiError(
            code="llm_bad_request",
            message="The backend generated an invalid LLM request.",
            status_code=500,
            retryable=exc.retryable,
        )
    if isinstance(exc, LLMMalformedResponseError):
        return _MappedApiError(
            code="llm_malformed_response",
            message="The configured LLM provider returned an invalid response.",
            status_code=502,
            retryable=exc.retryable,
        )
    if isinstance(exc, LLMStreamingError):
        return _MappedApiError(
            code="llm_streaming_error",
            message="The configured LLM stream failed.",
            status_code=503,
            retryable=exc.retryable,
        )
    if isinstance(exc, LLMCancelledError):
        return _MappedApiError(
            code="llm_cancelled",
            message="The configured LLM request was cancelled.",
            status_code=503,
            retryable=exc.retryable,
        )
    if isinstance(exc, LLMProviderUnavailableError):
        return _MappedApiError(
            code="llm_unavailable",
            message="The configured LLM provider is temporarily unavailable.",
            status_code=503,
            retryable=exc.retryable,
        )
    return _MappedApiError(
        code="llm_unavailable",
        message="The configured LLM provider is temporarily unavailable.",
        status_code=503,
        retryable=exc.retryable,
    )


def _map_memory_error(exc: MemoryGatewayError) -> _MappedApiError:
    if isinstance(exc, MemoryPolicyApprovalRequiredError):
        return _MappedApiError(
            code="policy_approval_required",
            message="The requested memory action requires approval.",
            status_code=403,
            retryable=False,
        )
    if isinstance(exc, MemoryDisabledError):
        return _MappedApiError(
            code="memory_disabled",
            message="Long-term memory is disabled for this backend.",
            status_code=503,
            retryable=False,
        )
    if isinstance(exc, MemoryInvalidScopeError):
        return _MappedApiError(
            code="memory_invalid_scope",
            message="The requested memory scope is invalid.",
            status_code=400,
            retryable=False,
        )
    if isinstance(exc, MemoryNotFoundError):
        return _MappedApiError(
            code="memory_not_found",
            message="The requested memory record was not found.",
            status_code=404,
            retryable=False,
        )
    if isinstance(exc, MemoryPrivacyError):
        return _MappedApiError(
            code="memory_privacy_error",
            message="The requested memory privacy operation could not be completed.",
            status_code=400,
            retryable=False,
        )
    if isinstance(exc, MemoryIngestionError):
        return _MappedApiError(
            code="memory_ingestion_failed",
            message="Document ingestion into long-term memory failed.",
            status_code=503,
            retryable=True,
        )
    if isinstance(exc, MemoryAdapterError):
        return _MappedApiError(
            code="memory_unavailable",
            message="The configured memory backend is temporarily unavailable.",
            status_code=503,
            retryable=True,
        )
    return _MappedApiError(
        code="memory_unavailable",
        message="The configured memory backend is temporarily unavailable.",
        status_code=503,
        retryable=True,
    )


def _map_tool_error(exc: ToolGatewayError) -> _MappedApiError:
    if isinstance(exc, ToolPolicyApprovalRequiredError):
        return _MappedApiError(
            code="policy_approval_required",
            message="The requested tool action requires approval.",
            status_code=403,
            retryable=False,
        )
    if isinstance(exc, ToolNotFoundError):
        return _MappedApiError(
            code="tool_not_found",
            message="The requested logical tool is not available.",
            status_code=404,
            retryable=False,
        )
    if isinstance(exc, ToolArgumentValidationError):
        return _MappedApiError(
            code="invalid_tool_arguments",
            message="The requested tool arguments are invalid.",
            status_code=400,
            retryable=False,
        )
    if isinstance(exc, ToolPolicyDeniedError):
        return _MappedApiError(
            code="policy_denied",
            message="The requested tool action is not allowed.",
            status_code=403,
            retryable=False,
        )
    if isinstance(exc, ToolDisabledError):
        return _MappedApiError(
            code="tool_disabled",
            message="The requested tool is disabled.",
            status_code=403,
            retryable=False,
        )
    if isinstance(exc, ToolResultTooLargeError):
        return _MappedApiError(
            code="tool_result_too_large",
            message="The tool returned more data than the backend can safely return.",
            status_code=502,
            retryable=False,
        )
    if isinstance(exc, ToolTimeoutError):
        return _MappedApiError(
            code="tool_timeout",
            message="The configured tool backend timed out.",
            status_code=504,
            retryable=True,
        )
    if isinstance(exc, ToolCancelledError):
        return _MappedApiError(
            code="tool_cancelled",
            message="The tool request was cancelled before completion.",
            status_code=503,
            retryable=True,
        )
    if isinstance(exc, MCPAuthenticationError):
        return _MappedApiError(
            code="tool_authentication_failed",
            message="The configured tool backend could not be authenticated.",
            status_code=503,
            retryable=True,
        )
    if isinstance(exc, MCPTransportError | MCPDiscoveryError):
        return _MappedApiError(
            code="tool_unavailable",
            message="The configured tool backend is temporarily unavailable.",
            status_code=503,
            retryable=True,
        )
    return _MappedApiError(
        code="tool_unavailable",
        message="The configured tool backend is temporarily unavailable.",
        status_code=503,
        retryable=True,
    )