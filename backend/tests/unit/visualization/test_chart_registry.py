from __future__ import annotations

import pytest

from app.visualization.chart_registry import ChartTypeRegistry
from app.visualization.errors import UnsupportedChartTypeError
from app.visualization.models import CANONICAL_CHART_TYPES
from app.visualization.renderer_capabilities import build_visualization_capability_snapshot


def test_chart_type_registry_preserves_v1_order_and_alias_resolution(
    visualization_registry: ChartTypeRegistry,
) -> None:
    assert visualization_registry.supported_types == CANONICAL_CHART_TYPES
    assert visualization_registry.normalize("trend chart") == "line"
    assert visualization_registry.normalize("box plot") == "box_plot"
    assert visualization_registry.resolve("grouped bar graph").display_name == "grouped bar"


def test_chart_type_registry_rejects_unsupported_chart_types(
    visualization_registry: ChartTypeRegistry,
) -> None:
    with pytest.raises(UnsupportedChartTypeError):
        visualization_registry.normalize("candlestick")


def test_chart_type_registry_rejects_aliases_that_override_canonical_types() -> None:
    with pytest.raises(ValueError, match="cannot override canonical chart type"):
        ChartTypeRegistry(aliases={"bar": "line"})


def test_renderer_capability_snapshot_covers_all_supported_v1_types(
    visualization_registry: ChartTypeRegistry,
    renderer_capability_catalog,
) -> None:
    snapshot = build_visualization_capability_snapshot(
        registry=visualization_registry,
        catalog=renderer_capability_catalog,
    )

    assert snapshot["supported_chart_types"] == list(CANONICAL_CHART_TYPES)
    assert snapshot["chart_type_count"] == len(CANONICAL_CHART_TYPES)
    assert snapshot["renderers"]["echarts"]["supported_chart_types"] == list(
        CANONICAL_CHART_TYPES
    )
    assert (
        snapshot["renderers"]["echarts"]["metadata"]["chart_type_matrix"]["bar"]
        == {
            "spec_versions": ["1.0"],
            "data_modes": ["inline"],
            "supports_reference_data": False,
        }
    )