"""Session lifecycle routes for the backend API boundary."""

from __future__ import annotations

import logging
from time import perf_counter

from fastapi import APIRouter, Body, Depends, Query, Response

from app.api.dependencies import (
    get_api_request_context,
    get_api_settings as get_api_settings_dependency,
    get_foundation_container,
    get_session_service,
)
from app.api.request_context import ApiRequestContext
from app.api.schemas import (
    ResetSessionRequest,
    ResetSessionResponse,
    SessionDeleteResponse,
    SessionHistoryResponse,
    SessionListResponse,
)
from app.api.errors import ApiError
from app.config.view import ApiSettings, SessionSettings
from app.foundation.container import FoundationContainer
from app.observability.events import SESSION_RESET
from app.session.errors import InvalidSessionIdError
from app.session.identifiers import normalize_session_id
from app.session.mapping import build_session_request_context
from app.session.models import SessionRequestContext
from app.session.service import SessionService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sessions"])


@router.post("/sessions/{session_id}/reset", response_model=ResetSessionResponse)
async def reset_session(
    session_id: str,
    response: Response,
    payload: ResetSessionRequest = Body(default_factory=ResetSessionRequest),
    context: ApiRequestContext = Depends(get_api_request_context),
    session_service: SessionService = Depends(get_session_service),
    api_settings: ApiSettings = Depends(get_api_settings_dependency),
    container: FoundationContainer = Depends(get_foundation_container),
) -> ResetSessionResponse:
    """Clear workflow state for one session through the session-service boundary."""

    session_settings = _require_session_settings(container)
    normalized_session_id = _normalize_session_id(session_id, session_settings=session_settings)
    session_context = _to_session_request_context(context)
    started_at = perf_counter()
    result = await session_service.reset_session(
        session_id=normalized_session_id,
        reason=payload.reason,
        context=session_context,
    )
    duration_ms = max(int((perf_counter() - started_at) * 1000), 0)

    reset_response = ResetSessionResponse.from_result(result)
    response.headers[api_settings.tracing.response_trace_header] = reset_response.trace_id
    response.headers[api_settings.sessions.session_id_header] = reset_response.session_id

    logger.info(
        "Session reset completed",
        extra={
            "component": "api.sessions",
            "event_type": SESSION_RESET,
            "status": "completed",
            "duration_ms": duration_ms,
            "details": {
                "route": "/sessions/{session_id}/reset",
                "session_id": reset_response.session_id,
                "reason": payload.reason,
            },
        },
    )
    await container.trace_recorder.record(
        event_type="session",
        event_name=SESSION_RESET,
        component="api.sessions",
        trace_id=reset_response.trace_id,
        session_id=reset_response.session_id,
        status="completed",
        duration_ms=float(duration_ms),
        payload={
            "route_template": "/sessions/{session_id}/reset",
            "reason": payload.reason,
        },
    )

    return reset_response


@router.get("/sessions/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(
    session_id: str,
    response: Response,
    limit: int | None = Query(default=None, ge=1),
    context: ApiRequestContext = Depends(get_api_request_context),
    session_service: SessionService = Depends(get_session_service),
    api_settings: ApiSettings = Depends(get_api_settings_dependency),
    container: FoundationContainer = Depends(get_foundation_container),
) -> SessionHistoryResponse:
    """Return safe bounded history for one session through the session-service boundary."""

    session_settings = _require_session_settings(container)
    normalized_session_id = _normalize_session_id(session_id, session_settings=session_settings)
    bounded_limit = _resolve_history_limit(limit=limit, session_settings=session_settings)
    session_context = _to_session_request_context(context)
    result = await session_service.get_history(
        session_id=normalized_session_id,
        limit=bounded_limit,
        context=session_context,
    )
    history_response = SessionHistoryResponse.from_result(result)
    response.headers[api_settings.tracing.response_trace_header] = history_response.trace_id
    response.headers[api_settings.sessions.session_id_header] = history_response.session_id
    return history_response


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    response: Response,
    limit: int | None = Query(default=None, ge=1),
    context: ApiRequestContext = Depends(get_api_request_context),
    session_service: SessionService = Depends(get_session_service),
    api_settings: ApiSettings = Depends(get_api_settings_dependency),
    container: FoundationContainer = Depends(get_foundation_container),
) -> SessionListResponse:
    """Return safe bounded session summaries through the session-service boundary."""

    session_settings = _require_session_settings(container)
    bounded_limit = _resolve_list_limit(limit=limit, session_settings=session_settings)
    session_context = _to_session_request_context(context)
    result = await session_service.list_sessions(limit=bounded_limit, context=session_context)
    list_response = SessionListResponse.from_result(result)
    response.headers[api_settings.tracing.response_trace_header] = list_response.trace_id
    return list_response


@router.delete("/sessions/{session_id}", response_model=SessionDeleteResponse)
async def delete_session(
    session_id: str,
    response: Response,
    context: ApiRequestContext = Depends(get_api_request_context),
    session_service: SessionService = Depends(get_session_service),
    api_settings: ApiSettings = Depends(get_api_settings_dependency),
    container: FoundationContainer = Depends(get_foundation_container),
) -> SessionDeleteResponse:
    """Delete one session through the session-service boundary."""

    session_settings = _require_session_settings(container)
    normalized_session_id = _normalize_session_id(session_id, session_settings=session_settings)
    session_context = _to_session_request_context(context)
    result = await session_service.delete_session(
        session_id=normalized_session_id,
        context=session_context,
    )
    delete_response = SessionDeleteResponse.from_result(result)
    response.headers[api_settings.tracing.response_trace_header] = delete_response.trace_id
    response.headers[api_settings.sessions.session_id_header] = delete_response.session_id
    return delete_response


def _normalize_session_id(raw_value: str, *, session_settings: SessionSettings) -> str:
    try:
        return normalize_session_id(
            raw_value,
            allowed_pattern=session_settings.identifiers.allowed_pattern,
            max_length=session_settings.identifiers.max_length,
        )
    except InvalidSessionIdError as exc:
        raise InvalidSessionIdError(
            details={
                "errors": [
                    {
                        "loc": ["path", "session_id"],
                        "msg": "Value error, invalid session_id",
                        "type": "value_error",
                    }
                ]
            },
        ) from exc


def _to_session_request_context(context: ApiRequestContext) -> SessionRequestContext:
    return build_session_request_context(
        trace_id=context.trace_id,
        request_id=context.request_id,
        user_id=context.user_id,
        user_id_hash=context.user_id_hash,
        client_host=context.client_host,
        user_agent=context.user_agent,
        path=context.path,
        method=context.method,
        metadata=context.metadata,
        headers_safe=context.headers_safe,
    )


def _require_session_settings(container: FoundationContainer) -> SessionSettings:
    session_settings = container.session_settings
    if not isinstance(session_settings, SessionSettings):
        raise RuntimeError("Session settings are not configured.")
    return session_settings


def _resolve_history_limit(*, limit: int | None, session_settings: SessionSettings) -> int:
    if limit is None:
        return session_settings.defaults.default_history_limit

    if limit > session_settings.defaults.max_history_limit:
        raise ApiError(
            code="validation_error",
            message="The request is invalid.",
            status_code=422,
            details={
                "errors": [
                    {
                        "loc": ["query", "limit"],
                        "msg": "Value error, limit exceeds the configured maximum",
                        "type": "value_error",
                    }
                ]
            },
        )

    return limit


def _resolve_list_limit(*, limit: int | None, session_settings: SessionSettings) -> int | None:
    if limit is None:
        return None

    if limit > session_settings.management.max_list_limit:
        raise ApiError(
            code="validation_error",
            message="The request is invalid.",
            status_code=422,
            details={
                "errors": [
                    {
                        "loc": ["query", "limit"],
                        "msg": "Value error, limit exceeds the configured maximum",
                        "type": "value_error",
                    }
                ]
            },
        )

    return limit