"""Foundation health route."""

from typing import Any, cast

from fastapi import APIRouter, Request

from app.foundation.container import FoundationContainer
from app.observability.events import HEALTH_CHECKED

router = APIRouter(tags=["foundation"])


@router.get("/health")
async def get_health(request: Request) -> dict[str, Any]:
    container = cast(FoundationContainer, request.app.state.container)
    include_details = bool(container.config.get("health.include_component_details", True))
    health_payload = await container.health.evaluate(
        include_details=include_details
    )
    await container.trace_recorder.record(
        event_type=HEALTH_CHECKED,
        component="api.health",
        trace_id=getattr(request.state, "trace_id", None),
        payload={
            "status": health_payload["status"],
            "include_details": include_details,
        },
    )
    return {
        "status": health_payload["status"],
        "service": container.config.require("app.name"),
        "version": container.settings.app_version,
        "environment": container.config.require("app.environment"),
        "checks": health_payload["checks"],
    }