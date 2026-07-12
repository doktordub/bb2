"""Visualization contracts, settings, and helpers for the backend chart slice."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_MODULES = (
    "app.visualization.artifact_store",
    "app.visualization.capabilities",
    "app.visualization.chart_data",
    "app.visualization.chart_registry",
    "app.visualization.chart_spec_builder",
    "app.visualization.chart_summary_builder",
    "app.visualization.computations",
    "app.visualization.context_selector",
    "app.visualization.gateway",
    "app.visualization.health",
    "app.visualization.models",
    "app.visualization.observability",
    "app.visualization.policy",
    "app.visualization.renderer_capabilities",
    "app.visualization.settings",
    "app.visualization.validators",
    "app.visualization.errors",
)

__all__ = [
    "CANONICAL_CHART_TYPES",
    "DEFAULT_VISUALIZATION_ALIASES",
    "DEFAULT_VISUALIZATION_SAFE_METADATA_ALLOWLIST",
    "ChartFieldProfile",
    "ChartSpecBuilder",
    "ChartSummaryBuilder",
    "DefaultVisualizationGateway",
    "InMemoryVisualizationArtifactStore",
    "StoredVisualizationArtifact",
    "SUPPORTED_CHART_RENDERERS",
    "SystemVisualizationArtifactClock",
    "VISUALIZATION_ARTIFACT_STORE_PROVIDERS",
    "VISUALIZATION_CONTEXT_SUMMARY_MODES",
    "VISUALIZATION_EVICTION_POLICIES",
    "ChartTypeDefinition",
    "ChartTypeRegistry",
    "ChartArtifact",
    "ChartArtifactBuildError",
    "ChartArtifactEnvelope",
    "ChartArtifactNotFoundError",
    "ChartComputedFacts",
    "ChartContextSummary",
    "ChartContextSummaryBuildError",
    "ChartContextSummaryLimitExceededError",
    "ChartDataMissingError",
    "ChartFieldProfile",
    "ChartDataSlice",
    "ChartDataValidationError",
    "ChartEncodingError",
    "ChartFollowupAmbiguousError",
    "ChartPolicyDeniedError",
    "ChartRequest",
    "ChartRowLimitExceededError",
    "ChartSeriesLimitExceededError",
    "ContextContribution",
    "NormalizedChartData",
    "RendererCapabilityCatalog",
    "RendererCapabilityRecord",
    "RendererCapabilities",
    "UnsupportedChartTypeError",
    "UnsupportedRendererError",
    "VisualizationArtifactStoreSqliteSettings",
    "VisualizationArtifactStoreSettings",
    "VisualizationArtifactScope",
    "VisualizationArtifactStore",
    "VisualizationArtifactClock",
    "VisualizationComputationService",
    "VisualizationContext",
    "VisualizationGateway",
    "VisualizationContextSummarySettings",
    "VisualizationError",
    "VisualizationLimitsSettings",
    "VisualizationBuildAuthorization",
    "VisualizationBuildAuthorizer",
    "VisualizationRetrievalAuthorization",
    "VisualizationRetrievalAuthorizer",
    "VisualizationRetrievalKind",
    "VisualizationRuntimeBundle",
    "VisualizationSampleDataSettings",
    "VisualizationSettings",
    "VisualizationGatewayObserver",
    "VisualizationPolicyAuthorizer",
    "build_visualization_gateway",
    "build_visualization_runtime",
    "build_visualization_health_payload",
    "build_visualization_capabilities_payload",
    "build_chart_context_contribution",
    "build_chart_computed_facts",
    "build_chart_data_slice",
    "collect_chart_summaries",
    "coerce_context_contribution",
    "merge_visualization_context",
    "build_renderer_capability_catalog",
    "build_safe_visualization_summary",
    "build_visualization_artifact_scope",
    "build_visualization_artifact_scope_from_context",
    "build_visualization_capability_snapshot",
    "build_visualization_error_message",
    "compare_chart_series",
    "count_unique_values",
    "estimate_chart_summary_tokens",
    "filter_chart_data_by_period",
    "infer_time_range",
    "lookup_exact_chart_value",
    "normalize_chart_data",
    "parse_temporal_value",
    "temporal_sort_key",
    "validate_chart_artifact",
    "validate_chart_context_contribution",
    "validate_chart_field_name",
    "validate_chart_context_summary",
    "select_chart_summaries_for_prompt",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    for module_name in _MODULES:
        module = import_module(module_name)
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)