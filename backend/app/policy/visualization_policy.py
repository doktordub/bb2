"""Visualization policy helpers for gateway authorization and safe capability exposure."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from app.contracts.config import ConfigurationView
from app.contracts.context import OrchestrationContext
from app.contracts.policy import (
    PolicyActor,
    PolicyDecision,
    PolicyEvaluationContext,
    PolicyRequest,
)
from app.policy.settings import PolicyProfileSettings
from app.policy.rule_matcher import is_name_allowed
from app.visualization.models import SUPPORTED_CHART_DATA_SOURCES, VisualizationContext

VisualizationPolicyAction = Literal["visualization.build", "visualization.retrieve"]


def build_visualization_policy_request(
    *,
    action: VisualizationPolicyAction,
    component: str,
    visualization_context: VisualizationContext,
    metadata: Mapping[str, Any],
) -> PolicyRequest:
    """Build a normalized policy request for visualization gateway operations."""

    actor = PolicyActor(
        actor_type="user" if visualization_context.user_id else "anonymous",
        actor_id=visualization_context.user_id or visualization_context.agent_name,
        user_id=visualization_context.user_id,
        tenant_id=_optional_text(visualization_context.policy_scope.get("tenant_id")),
        session_id=visualization_context.session_id,
    )
    evaluation = PolicyEvaluationContext(
        trace_id=visualization_context.trace_id,
        usecase_name=visualization_context.usecase,
        agent_name=visualization_context.agent_name,
        exposure_level="summary",
        tags=("visualization", action),
        metadata=dict(metadata),
    )
    scope = {
        "tenant_id": visualization_context.policy_scope.get("tenant_id"),
        "project_id": visualization_context.policy_scope.get("project_id"),
        "user_id": visualization_context.user_id,
        "session_id": visualization_context.session_id,
        "usecase_name": visualization_context.usecase,
        "agent_name": visualization_context.agent_name,
    }
    scope.update(_mapping_only(visualization_context.policy_scope))
    return PolicyRequest(
        action=action,
        component=component,
        resource=None,
        scope=scope,
        metadata=dict(metadata),
        actor=actor,
        evaluation=evaluation,
    )


async def evaluate_visualization_request(
    request: PolicyRequest,
    context: OrchestrationContext,
    profile: PolicyProfileSettings,
    config: ConfigurationView,
) -> PolicyDecision | None:
    """Evaluate visualization build and retrieval requests against profile limits."""

    _ = context
    _ = config

    if request.action not in {"visualization.build", "visualization.retrieve"}:
        return None

    settings = profile.visualization
    if not settings.enabled:
        return PolicyDecision.deny(
            reason="Visualization is disabled for this use case.",
            reason_code="policy.visualization.disabled",
        )

    chart_type = _optional_text(request.metadata.get("chart_type"))
    renderer = _optional_text(request.metadata.get("renderer"))
    data_source = _optional_text(request.metadata.get("data_source"))
    data_mode = _optional_text(request.metadata.get("data_mode"))
    stage = _optional_text(request.metadata.get("stage")) or "pre_build"
    return_type = _optional_text(request.metadata.get("return_type")) or "artifact"
    row_count = _optional_int(request.metadata.get("row_count"))
    series_count = _optional_int(request.metadata.get("series_count"))
    category_count = _optional_int(request.metadata.get("category_count"))
    summary_token_estimate = _optional_int(request.metadata.get("summary_token_estimate"))
    field_names = _text_tuple(request.metadata.get("field_names"))
    fields = _text_tuple(request.metadata.get("fields"))
    value_fields = _text_tuple(request.metadata.get("value_fields"))

    if settings.deny_unknown_chart_types and request.action == "visualization.build" and not chart_type:
        return PolicyDecision.deny(
            reason="Visualization requests must resolve to a supported chart type.",
            reason_code="policy.visualization.chart_type_required",
        )
    if chart_type and not is_name_allowed(settings.allowed_chart_types, chart_type):
        return PolicyDecision.deny(
            reason=f"Chart type '{chart_type}' is not allowed for this use case.",
            reason_code="policy.visualization.chart_type_denied",
            metadata={"resource": chart_type},
        )

    if settings.deny_unknown_renderers and request.action == "visualization.build" and not renderer:
        return PolicyDecision.deny(
            reason="Visualization requests must resolve to a supported renderer.",
            reason_code="policy.visualization.renderer_required",
        )
    if renderer and not is_name_allowed(settings.allowed_renderers, renderer):
        return PolicyDecision.deny(
            reason=f"Renderer '{renderer}' is not allowed for this use case.",
            reason_code="policy.visualization.renderer_denied",
            metadata={"resource": renderer},
        )

    if request.action == "visualization.build":
        if settings.require_data_source and (data_source is None or data_source in {"", "unknown"}):
            return PolicyDecision.deny(
                reason="Visualization requires an approved data source.",
                reason_code="policy.visualization.data_source_required",
            )
        source_decision = _evaluate_data_source(settings=settings, data_source=data_source)
        if source_decision is not None:
            return source_decision
        if data_mode == "reference" and not settings.allow_reference_data_mode:
            return PolicyDecision.deny(
                reason="Reference-mode chart delivery is not allowed for this use case.",
                reason_code="policy.visualization.reference_mode_denied",
            )
        if row_count is not None and row_count > settings.max_rows_artifact_store:
            return PolicyDecision.deny(
                reason="The chart dataset exceeds the allowed visualization row limit.",
                reason_code="policy.visualization.row_limit_exceeded",
                metadata={"row_count": row_count},
            )
        if stage in {"pre_build", "post_artifact"} and data_mode == "inline" and row_count is not None and row_count > settings.max_rows_inline:
            return PolicyDecision.deny(
                reason="The chart dataset is too large to return inline for this use case.",
                reason_code="policy.visualization.inline_row_limit_exceeded",
                metadata={"row_count": row_count},
            )
        if series_count is not None and series_count > settings.max_series:
            return PolicyDecision.deny(
                reason="The chart exceeds the allowed series limit for this use case.",
                reason_code="policy.visualization.series_limit_exceeded",
                metadata={"series_count": series_count},
            )
        if category_count is not None and category_count > settings.max_categories:
            return PolicyDecision.deny(
                reason="The chart exceeds the allowed category limit for this use case.",
                reason_code="policy.visualization.category_limit_exceeded",
                metadata={"category_count": category_count},
            )
        if stage == "post_summary" and summary_token_estimate is not None and summary_token_estimate > settings.max_context_summary_tokens:
            return PolicyDecision.deny(
                reason="The chart summary exceeds the allowed context budget for this use case.",
                reason_code="policy.visualization.summary_limit_exceeded",
                metadata={"summary_token_estimate": summary_token_estimate},
            )
        if _has_sensitive_fields(settings=settings, field_names=field_names):
            return PolicyDecision.deny(
                reason="The requested chart includes fields that are not allowed to be visualized.",
                reason_code="policy.visualization.sensitive_field_denied",
            )
        if settings.allow_full_dataset_in_context:
            return PolicyDecision.deny(
                reason="Full chart datasets are not allowed in prompt context.",
                reason_code="policy.visualization.full_dataset_context_denied",
            )
        return PolicyDecision.allow(
            reason_code="policy.visualization.allowed",
            metadata={
                "chart_type": chart_type,
                "renderer": renderer,
                "data_source": data_source,
                "stage": stage,
            },
        )

    if return_type in {"data_slice", "computed_facts"} and not settings.allow_exact_followup_retrieval:
        return PolicyDecision.deny(
            reason="Exact chart follow-up retrieval is not allowed for this use case.",
            reason_code="policy.visualization.followup_retrieval_denied",
        )
    if return_type == "data_slice" and not settings.allow_data_export:
        return PolicyDecision.deny(
            reason="Chart data export is not allowed for this use case.",
            reason_code="policy.visualization.data_export_denied",
        )
    if fields and _has_sensitive_fields(settings=settings, field_names=fields):
        return PolicyDecision.deny(
            reason="The requested chart fields are not allowed to be retrieved.",
            reason_code="policy.visualization.retrieval_sensitive_field_denied",
        )
    if value_fields and _has_sensitive_fields(settings=settings, field_names=value_fields):
        return PolicyDecision.deny(
            reason="The requested chart fields are not allowed to be retrieved.",
            reason_code="policy.visualization.retrieval_sensitive_field_denied",
        )
    if row_count is not None and row_count > settings.max_rows_artifact_store:
        return PolicyDecision.deny(
            reason="The requested chart retrieval exceeds the allowed row limit.",
            reason_code="policy.visualization.retrieval_row_limit_exceeded",
            metadata={"row_count": row_count},
        )
    return PolicyDecision.allow(
        reason_code="policy.visualization.allowed",
        metadata={
            "chart_type": chart_type,
            "renderer": renderer,
            "data_source": data_source,
            "return_type": return_type,
        },
    )


def _evaluate_data_source(*, settings: Any, data_source: str | None) -> PolicyDecision | None:
    if data_source is None:
        return None
    normalized = data_source.strip().lower()
    if normalized not in SUPPORTED_CHART_DATA_SOURCES:
        if settings.require_data_source:
            return PolicyDecision.deny(
                reason="Visualization requires an approved data source.",
                reason_code="policy.visualization.data_source_unknown",
                metadata={"resource": normalized},
            )
        return None
    if settings.allowed_data_sources and normalized not in settings.allowed_data_sources:
        return PolicyDecision.deny(
            reason=f"Data source '{normalized}' is not allowed for this use case.",
            reason_code="policy.visualization.data_source_denied",
            metadata={"resource": normalized},
        )
    if normalized == "memory" and not settings.allow_memory_data:
        return PolicyDecision.deny(
            reason="Memory data cannot be used for visualization in this use case.",
            reason_code="policy.visualization.memory_denied",
        )
    if normalized == "tool" and not settings.allow_tool_data:
        return PolicyDecision.deny(
            reason="Tool-derived data cannot be used for visualization in this use case.",
            reason_code="policy.visualization.tool_denied",
        )
    if normalized == "uploaded_file" and not settings.allow_uploaded_file_data:
        return PolicyDecision.deny(
            reason="Uploaded-file data cannot be used for visualization in this use case.",
            reason_code="policy.visualization.uploaded_file_denied",
        )
    return None


def _has_sensitive_fields(*, settings: Any, field_names: Sequence[str]) -> bool:
    if not settings.sensitive_fields:
        return False
    sensitive = {item.strip().lower() for item in settings.sensitive_fields}
    return any(item.strip().lower() in sensitive for item in field_names)


def _mapping_only(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()}


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value


def _text_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        current = item.strip()
        if current and current not in normalized:
            normalized.append(current)
    return tuple(normalized)