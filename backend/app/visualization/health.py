"""Safe visualization health payload builders."""

from __future__ import annotations

from typing import Any

from app.policy.settings import PolicyVisualizationSettings
from app.visualization.chart_registry import ChartTypeRegistry
from app.visualization.settings import VisualizationSettings


def build_visualization_health_payload(
    *,
    settings: VisualizationSettings,
    registry: ChartTypeRegistry,
    policy: PolicyVisualizationSettings | None = None,
) -> dict[str, Any]:
    """Build the safe `/health` visualization payload."""

    durable_replay_enabled = bool(
        settings.artifact_store.enabled
        and settings.artifact_store.provider.strip().lower() == "sqlite"
    )
    return {
        "configured": True,
        "enabled": bool(settings.enabled and (policy.enabled if policy is not None else True)),
        "default_renderer": settings.default_renderer,
        "supported_chart_types_count": len(registry.supported_types),
        "context_summary_enabled": settings.context_summary.enabled,
        "artifact_store_enabled": settings.artifact_store.enabled,
        "artifact_store_provider": settings.artifact_store.provider,
        "durable_replay_enabled": durable_replay_enabled,
    }