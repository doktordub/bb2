"""Visualization artifact retrieval routes for the backend API boundary."""

from __future__ import annotations

from collections.abc import Mapping
import logging

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencies import (
    get_api_request_context,
    get_api_settings as get_api_settings_dependency,
    get_foundation_container,
)
from app.api.errors import ApiError
from app.api.request_context import ApiRequestContext
from app.api.schemas import ArtifactResponse
from app.contracts.config import ConfigurationView
from app.config.view import ApiSettings, SessionSettings
from app.foundation.container import FoundationContainer
from app.session.errors import InvalidSessionIdError, SessionIdRequiredError
from app.session.identifiers import normalize_session_id
from app.visualization.errors import ChartArtifactNotFoundError, ChartDataMissingError
from app.visualization.gateway import VisualizationRetrievalKind
from app.visualization.models import VisualizationContext

logger = logging.getLogger(__name__)

router = APIRouter(tags=["artifacts"])


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    artifact_id: str,
    request: Request,
    response: Response,
    return_type: VisualizationRetrievalKind = Query(default="artifact"),
    field: list[str] | None = Query(default=None),
    value_field: list[str] | None = Query(default=None),
    max_rows: int | None = Query(default=None, ge=1),
    usecase: str | None = Query(default=None, min_length=1, max_length=100),
    context: ApiRequestContext = Depends(get_api_request_context),
    api_settings: ApiSettings = Depends(get_api_settings_dependency),
    container: FoundationContainer = Depends(get_foundation_container),
) -> ArtifactResponse:
    """Retrieve one stored visualization artifact or bounded exact-followup view."""

    session_settings = _require_session_settings(container)
    session_id = _resolve_session_id(
        request=request,
        api_settings=api_settings,
        session_settings=session_settings,
    )
    gateway = container.visualization_gateway
    if gateway is None:
        raise ApiError(
            code="artifact_retrieval_disabled",
            message="Artifact retrieval is not enabled.",
            status_code=404,
        )
    resolved_usecase = usecase or _default_usecase_name(container.config)
    resolved_agent_name = _resolve_agent_name(container.config, usecase_name=resolved_usecase)

    visualization_context = VisualizationContext(
        user_id=context.user_id,
        session_id=session_id,
        usecase=resolved_usecase,
        agent_name=resolved_agent_name,
        trace_id=context.trace_id,
        policy_scope={},
        config={},
    )

    try:
        result = await gateway.retrieve_chart_artifact(
            artifact_id,
            visualization_context,
            return_type=return_type,
            fields=field,
            max_rows=max_rows,
            value_fields=value_field,
        )
    except ChartArtifactNotFoundError as exc:
        raise ApiError(
            code="artifact_not_found",
            message="The requested artifact is not available.",
            status_code=404,
        ) from exc
    except ChartDataMissingError as exc:
        raise ApiError(
            code="artifact_unavailable",
            message="The requested artifact data is not available.",
            status_code=404,
        ) from exc

    response.headers[api_settings.tracing.response_trace_header] = context.trace_id
    response.headers[api_settings.sessions.session_id_header] = session_id
    response.headers["Cache-Control"] = _cache_control_header(container)

    metadata = {
        "return_type": return_type,
        "field_count": len(field or []),
    }
    if max_rows is not None:
        metadata["max_rows"] = max_rows

    logger.info(
        "Visualization artifact retrieved",
        extra={
            "component": "api.artifacts",
            "event_type": "artifact_retrieved",
            "status": "completed",
            "details": {
                "artifact_id": artifact_id,
                "return_type": return_type,
                "session_id": session_id,
            },
        },
    )

    return ArtifactResponse(
        trace_id=context.trace_id,
        session_id=session_id,
        data=result,
        metadata=metadata,
    )


def _require_session_settings(container: FoundationContainer) -> SessionSettings:
    session_settings = container.session_settings
    if not isinstance(session_settings, SessionSettings):
        raise RuntimeError("Session settings are not configured.")
    return session_settings


def _resolve_session_id(
    *,
    request: Request,
    api_settings: ApiSettings,
    session_settings: SessionSettings,
) -> str:
    header_name = api_settings.sessions.session_id_header
    raw_session_id = request.headers.get(header_name)
    if raw_session_id is None:
        raise SessionIdRequiredError(
            details={
                "errors": [
                    {
                        "loc": ["header", header_name],
                        "msg": "Value error, session_id is required",
                        "type": "value_error",
                    }
                ]
            }
        )
    try:
        return normalize_session_id(
            raw_session_id,
            allowed_pattern=session_settings.identifiers.allowed_pattern,
            max_length=session_settings.identifiers.max_length,
        )
    except InvalidSessionIdError as exc:
        raise InvalidSessionIdError(
            details={
                "errors": [
                    {
                        "loc": ["header", header_name],
                        "msg": "Value error, invalid session_id",
                        "type": "value_error",
                    }
                ]
            },
        ) from exc


def _cache_control_header(container: FoundationContainer) -> str:
    artifact_store = container.visualization_artifact_store
    ttl_seconds = 60
    if artifact_store is not None:
        settings = getattr(artifact_store, "settings", None)
        ttl_seconds = getattr(getattr(settings, "artifact_store", None), "ttl_seconds", ttl_seconds)
    bounded_ttl = max(1, min(int(ttl_seconds), 300))
    return f"private, max-age={bounded_ttl}"


def _default_usecase_name(config: ConfigurationView) -> str | None:
    value = config.get("app.active_usecase")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _resolve_agent_name(config: ConfigurationView, *, usecase_name: str | None) -> str:
    if usecase_name is not None:
        usecase_config = config.get(f"orchestration.usecases.{usecase_name}")
        if isinstance(usecase_config, Mapping):
            agent_name = usecase_config.get("agent")
            if isinstance(agent_name, str) and agent_name.strip():
                return agent_name.strip()
            strategy_name = usecase_config.get("strategy")
            if isinstance(strategy_name, str) and strategy_name.strip():
                strategy_config = config.get(f"orchestration.strategies.{strategy_name.strip()}")
                if isinstance(strategy_config, Mapping):
                    default_agent = strategy_config.get("default_agent")
                    if isinstance(default_agent, str) and default_agent.strip():
                        return default_agent.strip()

    default_agent = config.get("orchestration.defaults.default_agent")
    if isinstance(default_agent, str) and default_agent.strip():
        return default_agent.strip()

    return "support_agent"