"""Health routes for the backend API boundary."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.api.dependencies import get_api_request_context, get_foundation_container
from app.api.request_context import ApiRequestContext
from app.api.schemas import HealthResponse
from app.contracts.health import HEALTH_FAILED
from app.foundation.container import FoundationContainer
from app.foundation.health import build_api_health_payload
from app.observability.events import HEALTH_CHECKED

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def get_health(
    response: Response,
    context: ApiRequestContext = Depends(get_api_request_context),
    container: FoundationContainer = Depends(get_foundation_container),
) -> HealthResponse:
    include_details = bool(container.config.get("health.include_component_details", True))
    health_payload = await container.health.evaluate(include_details=include_details)
    response.status_code = 503 if health_payload["status"] == HEALTH_FAILED else 200
    await container.trace_recorder.record(
        event_type="health",
        event_name=HEALTH_CHECKED,
        component="api.health",
        trace_id=context.trace_id,
        status=(
            "completed"
            if health_payload["status"] == "ok"
            else "degraded" if health_payload["status"] == "degraded" else "failed"
        ),
        payload={
            "operation": "health",
            "status": health_payload["status"],
            "include_details": include_details,
        },
    )
    return HealthResponse.model_validate(
        build_api_health_payload(
            health_payload=health_payload,
            service_name=container.config.require("app.name"),
            version=container.settings.app_version,
            environment=container.config.require("app.environment"),
            trace_id=context.trace_id,
            api_settings=container.api_settings,
            streaming_enabled=bool(container.config.get("features.streaming_enabled", False)),
        )
    )