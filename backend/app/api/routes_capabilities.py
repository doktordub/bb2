"""Capabilities routes for the backend API boundary."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import (
    get_api_request_context,
    get_api_settings as get_api_settings_dependency,
    get_foundation_container,
)
from app.api.request_context import ApiRequestContext
from app.api.schemas import CapabilitiesResponse, CapabilitiesResponseData
from app.config.view import ApiSettings
from app.foundation.container import FoundationContainer

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities(
    context: ApiRequestContext = Depends(get_api_request_context),
    api_settings: ApiSettings = Depends(get_api_settings_dependency),
    container: FoundationContainer = Depends(get_foundation_container),
) -> CapabilitiesResponse:
    payload = await container.capabilities.describe_api(
        api_settings=api_settings,
        trace_id=context.trace_id,
        user_id=context.user_id,
    )
    return CapabilitiesResponse(
        trace_id=context.trace_id,
        data=CapabilitiesResponseData.model_validate(payload),
        metadata={},
    )