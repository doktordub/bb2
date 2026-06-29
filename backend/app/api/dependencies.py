"""Route dependency helpers for API request context and services."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from fastapi import Request

from app.api.request_context import ApiRequestContext
from app.api.security import ApiIdentity, build_local_identity
from app.config.view import ApiSettings
from app.deployment.process_control import ProcessControlService
from app.foundation.container import FoundationContainer
from app.observability.debug_trace_service import DebugTraceService
from app.observability.context import TraceContext
from app.observability.models import TRACE_ID_ALIAS_HEADER, TRACE_ID_HEADER
from app.session.service import SessionService

_SAFE_REQUEST_HEADERS = (
    TRACE_ID_HEADER,
    TRACE_ID_ALIAS_HEADER,
    "user-agent",
    "x-session-id",
)


def get_foundation_container(request: Request) -> FoundationContainer:
    """Return the initialized backend container from app state."""

    container = getattr(request.app.state, "container", None)
    if not isinstance(container, FoundationContainer):
        raise RuntimeError("Backend container is not initialized.")
    return container


def get_session_service(request: Request) -> SessionService:
    """Resolve the session service from the backend container."""

    container = get_foundation_container(request)
    session_service = container.session_service
    if session_service is None:
        raise RuntimeError("Session service is not configured.")
    return session_service


def get_api_settings(request: Request) -> ApiSettings:
    """Resolve typed API settings from the backend container."""

    container = get_foundation_container(request)
    api_settings = container.api_settings
    if not isinstance(api_settings, ApiSettings):
        raise RuntimeError("API settings are not configured.")
    return api_settings


def build_api_request_context(
    request: Request,
    *,
    identity: ApiIdentity | None = None,
) -> ApiRequestContext:
    """Construct a safe API request context from the active HTTP request."""

    trace_context = getattr(request.state, "trace_context", None)
    trace_id = _resolve_trace_id(request=request, trace_context=trace_context)
    request_id = _resolve_request_id(trace_context=trace_context, trace_id=trace_id)
    resolved_identity = identity or build_local_identity()
    client_host = request.client.host if request.client is not None else None
    headers_safe = _safe_headers(request.headers)
    user_agent = headers_safe.get("user-agent")

    return ApiRequestContext(
        trace_id=trace_id,
        request_id=request_id,
        user_id=resolved_identity.user_id,
        user_id_hash=resolved_identity.user_id_hash,
        client_host=client_host,
        user_agent=user_agent,
        path=request.url.path,
        method=request.method,
        headers_safe=headers_safe,
        metadata={
            "auth_mode": resolved_identity.auth_mode,
            "trace_id": trace_id,
            "request_id": request_id,
        },
    )


async def get_api_request_context(request: Request) -> ApiRequestContext:
    """FastAPI dependency that builds the public API request context."""

    return build_api_request_context(request)


def _resolve_trace_id(*, request: Request, trace_context: object) -> str:
    if isinstance(trace_context, TraceContext):
        return trace_context.trace_id

    trace_id = getattr(request.state, "trace_id", None)
    if isinstance(trace_id, str) and trace_id.strip():
        return trace_id

    raise RuntimeError("Request trace ID is missing.")


def _resolve_request_id(*, trace_context: object, trace_id: str) -> str:
    if isinstance(trace_context, TraceContext):
        request_id = trace_context.request_id
        if isinstance(request_id, str) and request_id.strip():
            return request_id
    return trace_id


def _safe_headers(headers: Mapping[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for header_name in _SAFE_REQUEST_HEADERS:
        value = headers.get(header_name)
        if value is None:
            continue
        safe[header_name] = value
    return safe


def get_optional_session_service(request: Request) -> SessionService | None:
    """Resolve the session service when present, otherwise return None."""

    container = get_foundation_container(request)
    return container.session_service


def get_optional_debug_trace_service(request: Request) -> object | None:
    """Resolve the optional debug-trace service from the backend container."""

    container = get_foundation_container(request)
    return container.debug_trace_service


def get_debug_trace_service(request: Request) -> DebugTraceService:
    """Resolve the configured debug-trace service from the backend container."""

    service = get_optional_debug_trace_service(request)
    if not _supports_debug_trace_service(service):
        raise RuntimeError("Debug trace service is not configured.")
    return cast(DebugTraceService, service)


def get_process_control_service(request: Request) -> ProcessControlService:
    """Resolve the configured process-control service from the backend container."""

    container = get_foundation_container(request)
    service = container.process_control_service
    if not isinstance(service, ProcessControlService):
        raise RuntimeError("Process control service is not configured.")
    return service


def _supports_debug_trace_service(service: object) -> bool:
    return callable(getattr(service, "read_trace", None)) and callable(
        getattr(service, "search_traces", None)
    )
