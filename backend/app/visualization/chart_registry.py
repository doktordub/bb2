"""Explicit chart-type registry and alias resolution for visualization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, cast

from app.visualization.errors import UnsupportedChartTypeError
from app.visualization.models import CANONICAL_CHART_TYPES, SupportedChartType


@dataclass(frozen=True, slots=True)
class ChartTypeDefinition:
    """Stable metadata for one canonical chart type."""

    name: SupportedChartType
    display_name: str
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "display_name", self.display_name.strip())
        object.__setattr__(self, "description", self.description.strip())


_V1_CHART_TYPE_DEFINITIONS: tuple[ChartTypeDefinition, ...] = (
    ChartTypeDefinition("bar", "bar", "Single-series categorical comparison."),
    ChartTypeDefinition(
        "grouped_bar",
        "grouped bar",
        "Multi-series categorical comparison with grouped bars.",
    ),
    ChartTypeDefinition(
        "stacked_bar",
        "stacked bar",
        "Multi-series categorical comparison with stacked contributions.",
    ),
    ChartTypeDefinition(
        "horizontal_bar",
        "horizontal bar",
        "Categorical comparison with horizontal orientation.",
    ),
    ChartTypeDefinition("line", "line", "Single-series ordered or time-series trend."),
    ChartTypeDefinition(
        "multi_line",
        "multi line",
        "Multi-series ordered or time-series trend.",
    ),
    ChartTypeDefinition("area", "area", "Filled trend comparison over an ordered axis."),
    ChartTypeDefinition("pie", "pie", "Part-to-whole comparison."),
    ChartTypeDefinition("donut", "donut", "Part-to-whole comparison with center cutout."),
    ChartTypeDefinition("scatter", "scatter", "Numeric x/y correlation plot."),
    ChartTypeDefinition("bubble", "bubble", "Numeric x/y plot with bubble size encoding."),
    ChartTypeDefinition("histogram", "histogram", "Distribution of one numeric field."),
    ChartTypeDefinition(
        "box_plot",
        "box plot",
        "Distribution summary for one numeric field.",
    ),
    ChartTypeDefinition(
        "heatmap",
        "heatmap",
        "Two-dimensional categorical grid with numeric intensity.",
    ),
    ChartTypeDefinition(
        "treemap",
        "treemap",
        "Hierarchical or categorical part-to-whole view.",
    ),
    ChartTypeDefinition(
        "waterfall",
        "waterfall",
        "Sequential positive and negative contributions.",
    ),
    ChartTypeDefinition(
        "gantt",
        "gantt",
        "Task schedule with start and end bounds.",
    ),
    ChartTypeDefinition(
        "radar",
        "radar",
        "Multi-metric comparison across repeated dimensions.",
    ),
    ChartTypeDefinition("table", "table", "Structured tabular output."),
)


def _normalize_lookup_key(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").replace("-", " ").split())


def _direct_lookup_keys(chart_type: SupportedChartType) -> tuple[str, ...]:
    normalized = _normalize_lookup_key(chart_type)
    return (normalized,)


class ChartTypeRegistry:
    """Explicit registry for canonical chart support and natural-language aliases."""

    def __init__(
        self,
        *,
        allowed_chart_types: Iterable[str] = CANONICAL_CHART_TYPES,
        aliases: Mapping[str, str] | None = None,
    ) -> None:
        definitions_by_name = {definition.name: definition for definition in _V1_CHART_TYPE_DEFINITIONS}
        allowed = tuple(dict.fromkeys(str(chart_type).strip() for chart_type in allowed_chart_types))
        unknown = sorted(chart_type for chart_type in allowed if chart_type not in definitions_by_name)
        if unknown:
            supported = ", ".join(CANONICAL_CHART_TYPES)
            raise ValueError(
                f"Unknown chart types in registry configuration: {', '.join(unknown)}. "
                f"Supported chart types: {supported}."
            )

        self._definitions_by_name = definitions_by_name
        self._supported_definitions = tuple(
            definitions_by_name[name]
            for name in CANONICAL_CHART_TYPES
            if name in allowed
        )
        if not self._supported_definitions:
            raise ValueError("ChartTypeRegistry requires at least one supported chart type.")

        self._supported_types = tuple(definition.name for definition in self._supported_definitions)
        self._alias_map, self._configured_aliases = self._build_aliases(aliases or {})

    @property
    def supported_types(self) -> tuple[SupportedChartType, ...]:
        return self._supported_types

    @property
    def configured_aliases(self) -> dict[str, SupportedChartType]:
        return dict(self._configured_aliases)

    def list(self) -> tuple[ChartTypeDefinition, ...]:
        return self._supported_definitions

    def supported_labels(self) -> tuple[str, ...]:
        return tuple(definition.display_name for definition in self._supported_definitions)

    def normalize(self, requested_type: str) -> SupportedChartType:
        if not isinstance(requested_type, str) or requested_type.strip() == "":
            raise UnsupportedChartTypeError(
                requested_type=str(requested_type),
                supported_types=self.supported_types,
            )

        normalized_lookup = _normalize_lookup_key(requested_type)
        chart_type = self._alias_map.get(normalized_lookup)
        if chart_type is None:
            raise UnsupportedChartTypeError(
                requested_type=requested_type,
                supported_types=self.supported_types,
            )
        return chart_type

    def resolve(self, requested_type: str) -> ChartTypeDefinition:
        return self.get(self.normalize(requested_type))

    def get(self, chart_type: str) -> ChartTypeDefinition:
        if chart_type not in self._definitions_by_name or chart_type not in self._supported_types:
            raise UnsupportedChartTypeError(
                requested_type=chart_type,
                supported_types=self.supported_types,
            )
        return self._definitions_by_name[cast(SupportedChartType, chart_type)]

    def is_supported(self, requested_type: str) -> bool:
        try:
            self.normalize(requested_type)
        except UnsupportedChartTypeError:
            return False
        return True

    def health_snapshot(self) -> dict[str, Any]:
        return {
            "chart_type_count": len(self._supported_definitions),
            "supported_chart_types": list(self.supported_types),
            "supported_chart_labels": list(self.supported_labels()),
            "configured_alias_count": len(self._configured_aliases),
            "configured_aliases": {
                alias: chart_type for alias, chart_type in sorted(self._configured_aliases.items())
            },
        }

    def _build_aliases(
        self,
        aliases: Mapping[str, str],
    ) -> tuple[dict[str, SupportedChartType], dict[str, SupportedChartType]]:
        direct_map: dict[str, SupportedChartType] = {}
        for definition in self._supported_definitions:
            for lookup_key in _direct_lookup_keys(definition.name):
                direct_map[lookup_key] = definition.name

        alias_map = dict(direct_map)
        configured_aliases: dict[str, SupportedChartType] = {}

        for raw_alias, raw_target in aliases.items():
            normalized_alias = _normalize_lookup_key(raw_alias)
            target = cast(SupportedChartType, raw_target)
            if target not in self._supported_types:
                raise ValueError(
                    f"Alias '{raw_alias}' maps to disabled chart type '{raw_target}'."
                )

            direct_target = direct_map.get(normalized_alias)
            if direct_target is not None and direct_target != target:
                raise ValueError(
                    f"Alias '{raw_alias}' cannot override canonical chart type '{direct_target}'."
                )

            existing_target = alias_map.get(normalized_alias)
            if existing_target is not None and existing_target != target:
                raise ValueError(
                    f"Alias '{raw_alias}' conflicts with existing chart mapping '{existing_target}'."
                )

            alias_map[normalized_alias] = target
            configured_aliases[normalized_alias] = target

        return alias_map, configured_aliases


__all__ = [
    "ChartTypeDefinition",
    "ChartTypeRegistry",
]