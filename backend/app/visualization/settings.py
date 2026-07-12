"""Typed visualization settings and safe summary helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.persistence.settings import SqliteStoreSettings
from app.visualization.models import CANONICAL_CHART_TYPES, SUPPORTED_CHART_RENDERERS

VISUALIZATION_CONTEXT_SUMMARY_MODES = ("summary_only",)
VISUALIZATION_ARTIFACT_STORE_PROVIDERS = ("disabled", "memory", "sqlite")
VISUALIZATION_EVICTION_POLICIES = ("most_recent", "most_recent_relevant")
DEFAULT_VISUALIZATION_SAFE_METADATA_ALLOWLIST = (
    "source",
    "source_agent",
    "currency",
    "unit",
    "usecase",
)
DEFAULT_VISUALIZATION_ALIASES = {
    "bar graph": "bar",
    "bar chart": "bar",
    "column chart": "bar",
    "grouped bar graph": "grouped_bar",
    "stacked bar graph": "stacked_bar",
    "line graph": "line",
    "trend chart": "line",
    "pie graph": "pie",
    "donut graph": "donut",
    "scatter plot": "scatter",
    "correlation plot": "scatter",
    "gantt chart": "gantt",
}


@dataclass(frozen=True, slots=True)
class VisualizationLimitsSettings:
    """Bounded chart sizing limits resolved from validated configuration."""

    max_rows_inline: int
    max_rows_artifact_store: int
    max_series: int
    max_categories: int
    max_artifact_bytes: int


@dataclass(frozen=True, slots=True)
class VisualizationSampleDataSettings:
    """Policy flags for opt-in sample data generation."""

    enabled: bool
    require_explicit_opt_in: bool
    max_rows: int


@dataclass(frozen=True, slots=True)
class VisualizationContextSummarySettings:
    """Prompt-safe chart summary settings resolved from validated configuration."""

    enabled: bool
    mode: str
    max_tokens_per_chart_summary: int
    max_chart_summaries_per_session_context: int
    max_total_visualization_context_tokens: int
    include_data_ref: bool
    include_aggregate_stats: bool
    include_extrema: bool
    include_trend_summary: bool
    include_sample_rows: bool
    max_sample_rows: int
    eviction_policy: str
    allow_full_dataset_in_context: bool


@dataclass(frozen=True, slots=True)
class VisualizationArtifactStoreSqliteSettings(SqliteStoreSettings):
    """Resolved SQLite settings for durable visualization artifact persistence."""


@dataclass(frozen=True, slots=True)
class VisualizationArtifactStoreSettings:
    """Session-scoped artifact store settings for charts and follow-up retrieval."""

    enabled: bool
    provider: str
    ttl_seconds: int
    allow_reference_data_mode: bool
    public_retrieval_enabled: bool
    retrieval_endpoint: str | None
    exact_followup_retrieval_enabled: bool
    sqlite: VisualizationArtifactStoreSqliteSettings | None = None


@dataclass(frozen=True, slots=True)
class VisualizationHistoryReplaySettings:
    """Bounded session-history replay settings for persisted chart artifacts."""

    enabled: bool = True
    prefer_inline: bool = True
    max_artifacts_per_message: int = 3
    max_inline_artifact_bytes: int = 65536
    max_total_bytes_per_message: int = 131072


@dataclass(frozen=True, slots=True)
class VisualizationSettings:
    """Typed visualization runtime settings resolved from validated configuration."""

    enabled: bool
    default_renderer: str
    allowed_renderers: tuple[str, ...]
    artifact_spec_version: str
    allowed_chart_types: tuple[str, ...]
    aliases: dict[str, str]
    safe_metadata_allowlist: tuple[str, ...]
    limits: VisualizationLimitsSettings
    sample_data: VisualizationSampleDataSettings
    context_summary: VisualizationContextSummarySettings
    artifact_store: VisualizationArtifactStoreSettings
    history_replay: VisualizationHistoryReplaySettings = field(
        default_factory=VisualizationHistoryReplaySettings
    )


def build_safe_visualization_summary(settings: VisualizationSettings) -> dict[str, Any]:
    """Return a frontend-safe visualization config summary for startup and health."""

    return {
        "enabled": settings.enabled,
        "default_renderer": settings.default_renderer,
        "allowed_renderers": list(settings.allowed_renderers),
        "artifact_spec_version": settings.artifact_spec_version,
        "supported_chart_types_count": len(settings.allowed_chart_types),
        "artifact_store_enabled": settings.artifact_store.enabled,
        "artifact_store_provider": settings.artifact_store.provider,
        "reference_mode_enabled": settings.artifact_store.allow_reference_data_mode,
        "exact_followup_retrieval_enabled": settings.artifact_store.exact_followup_retrieval_enabled,
        "history_replay_enabled": settings.history_replay.enabled,
        "history_replay_prefer_inline": settings.history_replay.prefer_inline,
        "history_replay_max_artifacts_per_message": (
            settings.history_replay.max_artifacts_per_message
        ),
        "context_summary_enabled": settings.context_summary.enabled,
        "context_summary_mode": settings.context_summary.mode,
        "context_summary_budget_tokens": settings.context_summary.max_total_visualization_context_tokens,
        "sample_data_enabled": settings.sample_data.enabled,
    }


__all__ = [
    "CANONICAL_CHART_TYPES",
    "DEFAULT_VISUALIZATION_ALIASES",
    "DEFAULT_VISUALIZATION_SAFE_METADATA_ALLOWLIST",
    "SUPPORTED_CHART_RENDERERS",
    "VISUALIZATION_ARTIFACT_STORE_PROVIDERS",
    "VISUALIZATION_CONTEXT_SUMMARY_MODES",
    "VISUALIZATION_EVICTION_POLICIES",
    "VisualizationArtifactStoreSqliteSettings",
    "VisualizationArtifactStoreSettings",
    "VisualizationContextSummarySettings",
    "VisualizationHistoryReplaySettings",
    "VisualizationLimitsSettings",
    "VisualizationSampleDataSettings",
    "VisualizationSettings",
    "build_safe_visualization_summary",
]