"""Foundation health route."""

from typing import Any, cast

from fastapi import APIRouter, Request

from app.foundation.container import FoundationContainer

router = APIRouter(tags=["foundation"])


@router.get("/health")
async def get_health(request: Request) -> dict[str, Any]:
    container = cast(FoundationContainer, request.app.state.container)
    health_payload = await container.health.evaluate()
    return {
        "status": health_payload["status"],
        "service": container.settings.app_name,
        "version": container.settings.app_version,
        "environment": container.settings.app_env,
        "checks": health_payload["checks"],
    }