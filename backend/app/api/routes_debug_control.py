"""Optional local debug control routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status

from app.api.debug_access import require_debug_access
from app.api.dependencies import (
    get_api_request_context,
    get_api_settings as get_api_settings_dependency,
    get_process_control_service,
)
from app.api.errors import ApiError
from app.api.request_context import ApiRequestContext
from app.api.schemas import RestartResponse
from app.config.view import ApiSettings
from app.deployment.process_control import ProcessControlService, RestartUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["debug"])


@router.post("/restart", response_model=RestartResponse, status_code=status.HTTP_202_ACCEPTED)
async def request_restart(
    background_tasks: BackgroundTasks,
    request: Request,
    response: Response,
    context: ApiRequestContext = Depends(get_api_request_context),
    api_settings: ApiSettings = Depends(get_api_settings_dependency),
    process_control_service: ProcessControlService = Depends(get_process_control_service),
) -> RestartResponse:
    require_debug_access(request=request, api_settings=api_settings)
    if not api_settings.debug_routes.restart_enabled:
        raise ApiError(
            code="not_found",
            message="Resource not found.",
            status_code=404,
        )

    try:
        receipt = process_control_service.prepare_restart_request(
            trace_id=context.trace_id,
            requested_by=context.user_id,
            client_host=context.client_host,
            route_path=request.url.path,
        )
    except RestartUnavailableError as exc:
        raise ApiError(
            code="restart_unavailable",
            message="Backend restart is not configured for the current runtime.",
            status_code=503,
        ) from exc

    background_tasks.add_task(process_control_service.dispatch_restart)
    response.headers[api_settings.tracing.response_trace_header] = context.trace_id

    logger.info(
        "Backend restart requested",
        extra={
            "component": "api.debug_control",
            "event_type": "restart_requested",
            "status": "accepted",
            "details": {
                "route": "/restart",
                "request_id": receipt.request_id,
                "client_host": context.client_host,
            },
        },
    )

    return RestartResponse.from_receipt(trace_id=context.trace_id, receipt=receipt)