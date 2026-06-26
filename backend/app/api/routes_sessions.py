"""Session lifecycle routes for the backend API boundary."""

from __future__ import annotations

import logging
from time import perf_counter

from fastapi import APIRouter, Body, Depends, Response

from app.api.dependencies import (
    get_api_request_context,
    get_api_settings as get_api_settings_dependency,
    get_foundation_container,
    get_session_service,
)
from app.api.errors import ApiError
from app.api.request_context import ApiRequestContext
from app.api.schemas import ResetSessionRequest, ResetSessionResponse
from app.config.view import ApiSettings
from app.contracts.state import normalize_workflow_state_session_id
from app.foundation.container import FoundationContainer
from app.observability.events import SESSION_RESET
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

    normalized_session_id = _normalize_session_id(session_id)
    started_at = perf_counter()
    result = await session_service.reset_session(
        session_id=normalized_session_id,
        reason=payload.reason,
        context=context,
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


def _normalize_session_id(raw_value: str) -> str:
    try:
        return normalize_workflow_state_session_id(raw_value)
    except ValueError as exc:
        raise ApiError(
            code="invalid_session_id",
            message="The session ID is invalid.",
            status_code=400,
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