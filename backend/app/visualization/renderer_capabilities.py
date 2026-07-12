"""Renderer capability records for visualization chart validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from app.visualization.chart_registry import ChartTypeRegistry
from app.visualization.errors import UnsupportedRendererError
from app.visualization.models import ChartDataMode, ChartRenderer, RendererCapabilities, SupportedChartType
from app.visualization.settings import VisualizationSettings

_INLINE_DATA_MODE: tuple[ChartDataMode, ...] = ("inline",)
_INLINE_AND_REFERENCE_DATA_MODES: tuple[ChartDataMode, ...] = ("inline", "reference")


@dataclass(frozen=True, slots=True)
class RendererCapabilityRecord:
    """Stable per-chart renderer capability record keyed by spec version."""

    renderer: ChartRenderer
    chart_type: SupportedChartType
    spec_version: str
    supported_data_modes: tuple[ChartDataMode, ...] = _INLINE_DATA_MODE
    supports_reference_data: bool = False
    max_series: int | None = None
    max_categories: int | None = None

    def supports(self, *, data_mode: str | None = None) -> bool:
        return data_mode is None or data_mode in self.supported_data_modes


class RendererCapabilityCatalog:
    """Lookup surface for renderer/chart/spec compatibility."""

    def __init__(self, records: tuple[RendererCapabilityRecord, ...]) -> None:
        if not records:
            raise ValueError("RendererCapabilityCatalog requires at least one capability record.")

        index: dict[tuple[str, str, str], RendererCapabilityRecord] = {}
        renderers: list[str] = []
        for record in records:
            key = (record.renderer, record.chart_type, record.spec_version)
            if key in index:
                raise ValueError(
                    "Duplicate renderer capability record for "
                    f"renderer='{record.renderer}', chart_type='{record.chart_type}', "
                    f"spec_version='{record.spec_version}'."
                )
            index[key] = record
            if record.renderer not in renderers:
                renderers.append(record.renderer)

        self._records = records
        self._index = index
        self._renderers = tuple(renderers)

    def renderers(self) -> tuple[str, ...]:
        return self._renderers

    def lookup(
        self,
        *,
        renderer: str,
        chart_type: str,
        spec_version: str,
    ) -> RendererCapabilityRecord | None:
        return self._index.get((renderer, chart_type, spec_version))

    def supports(
        self,
        *,
        renderer: str,
        chart_type: str,
        spec_version: str,
        data_mode: str | None = None,
    ) -> bool:
        record = self.lookup(
            renderer=renderer,
            chart_type=chart_type,
            spec_version=spec_version,
        )
        return record is not None and record.supports(data_mode=data_mode)

    def describe_renderer(self, renderer: str) -> RendererCapabilities:
        if renderer not in self._renderers:
            raise UnsupportedRendererError(renderer=renderer, supported_renderers=self._renderers)

        records = tuple(record for record in self._records if record.renderer == renderer)
        spec_versions = sorted({record.spec_version for record in records})
        chart_types = list(dict.fromkeys(record.chart_type for record in records))
        supported_data_modes = sorted(
            {data_mode for record in records for data_mode in record.supported_data_modes}
        )
        max_series_values = [record.max_series for record in records if record.max_series is not None]
        max_category_values = [
            record.max_categories for record in records if record.max_categories is not None
        ]

        chart_type_matrix: dict[str, dict[str, Any]] = {}
        for chart_type in chart_types:
            chart_records = [record for record in records if record.chart_type == chart_type]
            chart_type_matrix[chart_type] = {
                "spec_versions": sorted({record.spec_version for record in chart_records}),
                "data_modes": sorted(
                    {
                        data_mode
                        for record in chart_records
                        for data_mode in record.supported_data_modes
                    }
                ),
                "supports_reference_data": any(
                    record.supports_reference_data for record in chart_records
                ),
            }

        return RendererCapabilities(
            renderer=cast(ChartRenderer, renderer),
            supported_spec_versions=spec_versions,
            supported_chart_types=[cast(SupportedChartType, chart_type) for chart_type in chart_types],
            supported_data_modes=[cast(ChartDataMode, mode) for mode in supported_data_modes],
            supports_reference_data="reference" in supported_data_modes,
            max_series=(min(max_series_values) if max_series_values else None),
            max_categories=(min(max_category_values) if max_category_values else None),
            metadata={
                "chart_type_matrix": chart_type_matrix,
            },
        )


def build_renderer_capability_catalog(
    *,
    settings: VisualizationSettings,
    registry: ChartTypeRegistry,
) -> RendererCapabilityCatalog:
    """Build the phase-2 renderer capability matrix from validated settings."""

    supports_reference_data = bool(
        settings.artifact_store.allow_reference_data_mode
        and settings.artifact_store.public_retrieval_enabled
        and settings.artifact_store.retrieval_endpoint
    )
    supported_data_modes = (
        _INLINE_AND_REFERENCE_DATA_MODES if supports_reference_data else _INLINE_DATA_MODE
    )

    records = tuple(
        RendererCapabilityRecord(
            renderer=cast(ChartRenderer, renderer),
            chart_type=chart_type,
            spec_version=settings.artifact_spec_version,
            supported_data_modes=supported_data_modes,
            supports_reference_data=supports_reference_data,
            max_series=settings.limits.max_series,
            max_categories=settings.limits.max_categories,
        )
        for renderer in settings.allowed_renderers
        for chart_type in registry.supported_types
    )
    return RendererCapabilityCatalog(records)


def build_visualization_capability_snapshot(
    *,
    registry: ChartTypeRegistry,
    catalog: RendererCapabilityCatalog,
) -> dict[str, Any]:
    """Build a safe internal snapshot for later health and capability aggregation."""

    return {
        "chart_type_count": len(registry.supported_types),
        "supported_chart_types": list(registry.supported_types),
        "configured_alias_count": len(registry.configured_aliases),
        "renderers": {
            renderer: catalog.describe_renderer(renderer).model_dump(mode="json")
            for renderer in catalog.renderers()
        },
    }


__all__ = [
    "RendererCapabilityCatalog",
    "RendererCapabilityRecord",
    "build_renderer_capability_catalog",
    "build_visualization_capability_snapshot",
]