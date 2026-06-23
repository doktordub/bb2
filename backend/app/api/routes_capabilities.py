"""Foundation capabilities route."""

from typing import Any, cast

from fastapi import APIRouter, Request

from app.foundation.container import FoundationContainer

router = APIRouter(tags=["foundation"])


@router.get("/capabilities")
async def get_capabilities(request: Request) -> dict[str, Any]:
    container = cast(FoundationContainer, request.app.state.container)
    return container.capabilities.describe()