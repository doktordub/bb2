"""Visualization gateway policy authorizers built on the shared policy service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.contracts.config import ConfigurationView
from app.contracts.policy import PolicyService
from app.policy.context import build_readonly_policy_context
from app.policy.visualization_policy import build_visualization_policy_request
from app.visualization.models import VisualizationContext

if TYPE_CHECKING:
    from app.visualization.gateway import (
        VisualizationBuildAuthorization,
        VisualizationRetrievalAuthorization,
    )


@dataclass(frozen=True, slots=True)
class VisualizationPolicyAuthorizer:
    """Adapter that turns gateway authorization requests into policy evaluations."""

    policy_service: PolicyService
    config: ConfigurationView
    component: str = "app.visualization.gateway"

    async def authorize_build(self, request: VisualizationBuildAuthorization) -> None:
        await self.policy_service.require_allowed(
            build_visualization_policy_request(
                action="visualization.build",
                component=self.component,
                visualization_context=request.context,
                metadata=_build_request_metadata(request),
            ),
            _build_context(
                policy_service=self.policy_service,
                config=self.config,
                context=request.context,
            ),
        )

    async def authorize_retrieval(self, request: VisualizationRetrievalAuthorization) -> None:
        await self.policy_service.require_allowed(
            build_visualization_policy_request(
                action="visualization.retrieve",
                component=self.component,
                visualization_context=request.context,
                metadata={
                    "artifact_id": request.artifact_id,
                    "return_type": request.return_type,
                    "fields": list(request.fields),
                    "value_fields": list(request.value_fields),
                    "row_count": request.max_rows,
                    "field_names": list(request.fields),
                },
            ),
            _build_context(
                policy_service=self.policy_service,
                config=self.config,
                context=request.context,
            ),
        )


def _build_context(
    *,
    policy_service: PolicyService,
    config: ConfigurationView,
    context: VisualizationContext,
):
    return build_readonly_policy_context(
        policy_service=policy_service,
        config=config,
        trace_id=context.trace_id,
        user_id=context.user_id,
        session_id=context.session_id,
        usecase_name=context.usecase,
    )


def _build_request_metadata(request: VisualizationBuildAuthorization) -> dict[str, Any]:
    field_names = list(request.normalized_data.fields)
    row_count = request.normalized_data.row_count
    series_count = _series_count(request)
    category_count = _category_count(request)
    data_mode = None
    summary_token_estimate = request.summary_token_estimate
    if request.artifact is not None:
        data_mode = request.artifact.data_mode

    metadata: dict[str, Any] = {
        "stage": request.stage,
        "chart_type": request.request.chart_type,
        "renderer": request.renderer,
        "data_source": request.request.data_source,
        "row_count": row_count,
        "series_count": series_count,
        "category_count": category_count,
        "field_names": field_names,
        "allow_full_dataset_in_context": False,
    }
    if data_mode is not None:
        metadata["data_mode"] = data_mode
    if summary_token_estimate is not None:
        metadata["summary_token_estimate"] = summary_token_estimate
    return metadata


def _series_count(request: VisualizationBuildAuthorization) -> int:
    if request.request.y_fields:
        return len(request.request.y_fields)
    series_field = request.request.series_field
    if not series_field:
        return 1
    profile = request.normalized_data.field_profiles.get(series_field)
    if profile is None:
        return 0
    return max(profile.distinct_count, 1)


def _category_count(request: VisualizationBuildAuthorization) -> int:
    category_field = request.request.category_field or request.request.x_field
    if not category_field:
        return 0
    profile = request.normalized_data.field_profiles.get(category_field)
    if profile is None:
        return 0
    return profile.distinct_count