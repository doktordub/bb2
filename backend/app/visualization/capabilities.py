"""Frontend-safe visualization capability payload builders."""

from __future__ import annotations

from app.policy.settings import PolicyVisualizationSettings
from app.visualization.chart_registry import ChartTypeRegistry
from app.visualization.settings import VisualizationSettings


def build_visualization_capabilities_payload(
    *,
    settings: VisualizationSettings,
    registry: ChartTypeRegistry,
    policy: PolicyVisualizationSettings | None = None,
) -> dict[str, object]:
    """Build the frontend-safe visualization capability payload."""

    effective_renderers = [
        renderer
        for renderer in settings.allowed_renderers
        if policy is None or not policy.allowed_renderers or renderer in policy.allowed_renderers
    ]
    effective_chart_types = [
        chart_type
        for chart_type in registry.supported_types
        if policy is None or not policy.allowed_chart_types or chart_type in policy.allowed_chart_types
    ]
    reference_mode_supported = bool(
        settings.artifact_store.allow_reference_data_mode
        and settings.artifact_store.public_retrieval_enabled
        and settings.artifact_store.retrieval_endpoint
    )
    durable_replay_enabled = bool(
        settings.artifact_store.enabled
        and settings.artifact_store.provider.strip().lower() == "sqlite"
    )
    return {
        "enabled": bool(settings.enabled and (policy.enabled if policy is not None else True)),
        "default_renderer": settings.default_renderer,
        "allowed_renderers": effective_renderers,
        "spec_version": settings.artifact_spec_version,
        "context_summary_mode": settings.context_summary.mode if settings.context_summary.enabled else "disabled",
        "supported_chart_types": effective_chart_types,
        "reference_mode_supported": reference_mode_supported,
        "reference_mode_enabled": bool(reference_mode_supported and (policy.allow_reference_data_mode if policy is not None else True)),
        "artifact_store_enabled": settings.artifact_store.enabled,
        "artifact_store_provider": settings.artifact_store.provider,
        "durable_replay_enabled": durable_replay_enabled,
        "exact_followup_retrieval_enabled": bool(
            settings.artifact_store.exact_followup_retrieval_enabled
            and (policy.allow_exact_followup_retrieval if policy is not None else True)
        ),
        "limits": {
            "max_rows_inline": min(settings.limits.max_rows_inline, policy.max_rows_inline) if policy is not None else settings.limits.max_rows_inline,
            "max_rows_artifact_store": min(settings.limits.max_rows_artifact_store, policy.max_rows_artifact_store) if policy is not None else settings.limits.max_rows_artifact_store,
            "max_series": min(settings.limits.max_series, policy.max_series) if policy is not None else settings.limits.max_series,
            "max_categories": min(settings.limits.max_categories, policy.max_categories) if policy is not None else settings.limits.max_categories,
            "max_context_summary_tokens": min(settings.context_summary.max_tokens_per_chart_summary, policy.max_context_summary_tokens) if policy is not None else settings.context_summary.max_tokens_per_chart_summary,
            "max_artifacts_per_response": policy.max_artifacts_per_response if policy is not None else 1,
        },
    }