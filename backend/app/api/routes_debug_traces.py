"""Optional local debug trace routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import (
    get_api_request_context,
    get_api_settings as get_api_settings_dependency,
    get_debug_trace_service,
)
from app.api.errors import ApiError
from app.api.request_context import ApiRequestContext
from app.api.versioning import API_SCHEMA_VERSION
from app.config.view import ApiSettings
from app.observability.debug_trace_service import DebugTraceService

_LOCALHOST_NAMES = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})

router = APIRouter(tags=["debug"])


@router.get("/debug/traces/{trace_id}")
async def get_debug_trace(
    trace_id: str,
    request: Request,
    limit: int | None = Query(default=None, ge=1),
    context: ApiRequestContext = Depends(get_api_request_context),
    api_settings: ApiSettings = Depends(get_api_settings_dependency),
    debug_trace_service: DebugTraceService = Depends(get_debug_trace_service),
) -> dict[str, Any]:
    _require_debug_access(request=request, api_settings=api_settings)
    result = await debug_trace_service.read_trace(trace_id=trace_id, limit=limit)
    if not bool(result.get("found", False)):
        raise ApiError(
            code="trace_not_found",
            message="The requested trace was not found.",
            status_code=404,
        )

    return {
        "schema_version": API_SCHEMA_VERSION,
        "trace_id": context.trace_id,
        "data": result["data"],
        "metadata": result["metadata"],
    }


@router.get("/debug/traces")
async def search_debug_traces(
    request: Request,
    status: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
    errors_only: bool = Query(default=False),
    usecase: str | None = Query(default=None),
    event_name: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    context: ApiRequestContext = Depends(get_api_request_context),
    api_settings: ApiSettings = Depends(get_api_settings_dependency),
    debug_trace_service: DebugTraceService = Depends(get_debug_trace_service),
) -> dict[str, Any]:
    _require_debug_access(request=request, api_settings=api_settings)
    result = await debug_trace_service.search_traces(
        status=status,
        limit=limit,
        errors_only=errors_only,
        usecase=usecase,
        event_name=event_name,
        event_type=event_type,
    )
    return {
        "schema_version": API_SCHEMA_VERSION,
        "trace_id": context.trace_id,
        "data": result["data"],
        "metadata": result["metadata"],
    }


def _require_debug_access(*, request: Request, api_settings: ApiSettings) -> None:
    if not api_settings.debug_routes.enabled:
        raise ApiError(
            code="not_found",
            message="Resource not found.",
            status_code=404,
        )

    if not api_settings.debug_routes.require_localhost:
        return

    client_host = request.client.host if request.client is not None else None
    if client_host in _LOCALHOST_NAMES:
        return

    raise ApiError(
        code="debug_access_denied",
        message="Debug trace routes require localhost access.",
        status_code=403,
    )