from __future__ import annotations

from pathlib import Path

import pytest

from app.visualization.chart_registry import ChartTypeRegistry
from app.visualization.models import CANONICAL_CHART_TYPES
from app.visualization.renderer_capabilities import (
    RendererCapabilityCatalog,
    build_renderer_capability_catalog,
)
from app.visualization.settings import (
    DEFAULT_VISUALIZATION_ALIASES,
    DEFAULT_VISUALIZATION_SAFE_METADATA_ALLOWLIST,
    VisualizationArtifactStoreSqliteSettings,
    VisualizationArtifactStoreSettings,
    VisualizationContextSummarySettings,
    VisualizationLimitsSettings,
    VisualizationSampleDataSettings,
    VisualizationSettings,
)

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "visualization"


@pytest.fixture
def visualization_fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture
def visualization_settings() -> VisualizationSettings:
    return VisualizationSettings(
        enabled=True,
        default_renderer="echarts",
        allowed_renderers=("echarts",),
        artifact_spec_version="1.0",
        allowed_chart_types=CANONICAL_CHART_TYPES,
        aliases=dict(DEFAULT_VISUALIZATION_ALIASES),
        safe_metadata_allowlist=DEFAULT_VISUALIZATION_SAFE_METADATA_ALLOWLIST,
        limits=VisualizationLimitsSettings(
            max_rows_inline=500,
            max_rows_artifact_store=5000,
            max_series=12,
            max_categories=100,
            max_artifact_bytes=262144,
        ),
        sample_data=VisualizationSampleDataSettings(
            enabled=False,
            require_explicit_opt_in=True,
            max_rows=25,
        ),
        context_summary=VisualizationContextSummarySettings(
            enabled=True,
            mode="summary_only",
            max_tokens_per_chart_summary=600,
            max_chart_summaries_per_session_context=5,
            max_total_visualization_context_tokens=1800,
            include_data_ref=True,
            include_aggregate_stats=True,
            include_extrema=True,
            include_trend_summary=True,
            include_sample_rows=False,
            max_sample_rows=0,
            eviction_policy="most_recent_relevant",
            allow_full_dataset_in_context=False,
        ),
        artifact_store=VisualizationArtifactStoreSettings(
            enabled=True,
            provider="sqlite",
            ttl_seconds=7200,
            allow_reference_data_mode=False,
            public_retrieval_enabled=False,
            retrieval_endpoint="/artifacts/{artifact_id}",
            exact_followup_retrieval_enabled=True,
            sqlite=VisualizationArtifactStoreSqliteSettings(
                path=Path("visualization_artifacts.db"),
                create_parent_dirs=True,
                initialize_schema=True,
                journal_mode="WAL",
                synchronous="NORMAL",
                busy_timeout_ms=5000,
                foreign_keys=True,
                required=True,
            ),
        ),
    )


@pytest.fixture
def visualization_registry(visualization_settings: VisualizationSettings) -> ChartTypeRegistry:
    return ChartTypeRegistry(
        allowed_chart_types=visualization_settings.allowed_chart_types,
        aliases=visualization_settings.aliases,
    )


@pytest.fixture
def renderer_capability_catalog(
    visualization_settings: VisualizationSettings,
    visualization_registry: ChartTypeRegistry,
) -> RendererCapabilityCatalog:
    return build_renderer_capability_catalog(
        settings=visualization_settings,
        registry=visualization_registry,
    )