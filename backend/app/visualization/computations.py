"""Deterministic chart computations used for exact follow-up retrieval."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from app.visualization.chart_data import (
    NormalizedChartData,
    normalize_chart_data,
    parse_temporal_value,
    temporal_sort_key,
    validate_chart_field_name,
)
from app.visualization.chart_registry import ChartTypeRegistry
from app.visualization.chart_spec_builder import ChartSpecBuilder
from app.visualization.errors import ChartDataValidationError, ChartFollowupAmbiguousError
from app.visualization.models import (
    ChartArtifact,
    ChartComputedFacts,
    ChartDataSlice,
    ChartRequest,
    VisualizationContext,
)
from app.visualization.renderer_capabilities import RendererCapabilityCatalog
from app.visualization.settings import VisualizationSettings

_SEQUENCE_TYPES = (list, tuple, set, frozenset)


@dataclass(slots=True)
class VisualizationComputationService:
    """Reusable deterministic chart helpers for retrieval and chart reuse."""

    settings: VisualizationSettings
    registry: ChartTypeRegistry
    capability_catalog: RendererCapabilityCatalog

    def build_data_slice(
        self,
        *,
        artifact: ChartArtifact,
        data: Sequence[Mapping[str, Any]] | NormalizedChartData,
        fields: Sequence[str] | None = None,
        filters: Mapping[str, Any] | None = None,
        max_rows: int | None = None,
        data_ref: str | None = None,
    ) -> ChartDataSlice:
        return build_chart_data_slice(
            artifact,
            data,
            fields=fields,
            filters=filters,
            max_rows=max_rows,
            data_ref=data_ref,
        )

    def compute_facts(
        self,
        *,
        artifact: ChartArtifact,
        data: Sequence[Mapping[str, Any]] | NormalizedChartData,
        filters: Mapping[str, Any] | None = None,
        value_fields: Sequence[str] | None = None,
        summary_text: str | None = None,
        data_ref: str | None = None,
    ) -> ChartComputedFacts:
        return build_chart_computed_facts(
            artifact,
            data,
            filters=filters,
            value_fields=value_fields,
            summary_text=summary_text,
            data_ref=data_ref,
        )

    def lookup_exact_value(
        self,
        *,
        artifact: ChartArtifact,
        data: Sequence[Mapping[str, Any]] | NormalizedChartData,
        match_field: str,
        match_value: Any,
        value_field: str,
        series_field: str | None = None,
        series_value: Any | None = None,
        data_ref: str | None = None,
    ) -> ChartComputedFacts:
        return lookup_exact_chart_value(
            artifact,
            data,
            match_field=match_field,
            match_value=match_value,
            value_field=value_field,
            series_field=series_field,
            series_value=series_value,
            data_ref=data_ref,
        )

    def filter_by_period(
        self,
        *,
        artifact: ChartArtifact,
        data: Sequence[Mapping[str, Any]] | NormalizedChartData,
        field_name: str,
        start: str | date | datetime | time | None = None,
        end: str | date | datetime | time | None = None,
        fields: Sequence[str] | None = None,
        max_rows: int | None = None,
        data_ref: str | None = None,
    ) -> ChartDataSlice:
        return filter_chart_data_by_period(
            artifact,
            data,
            field_name=field_name,
            start=start,
            end=end,
            fields=fields,
            max_rows=max_rows,
            data_ref=data_ref,
        )

    def compare_series(
        self,
        *,
        artifact: ChartArtifact,
        data: Sequence[Mapping[str, Any]] | NormalizedChartData,
        series_field: str,
        left_series: Any,
        right_series: Any,
        value_field: str,
        x_field: str | None = None,
        data_ref: str | None = None,
    ) -> ChartComputedFacts:
        return compare_chart_series(
            artifact,
            data,
            series_field=series_field,
            left_series=left_series,
            right_series=right_series,
            value_field=value_field,
            x_field=x_field,
            data_ref=data_ref,
        )

    def reuse_chart_data_for_request(
        self,
        *,
        request: ChartRequest,
        data: Sequence[Mapping[str, Any]] | NormalizedChartData,
        context: VisualizationContext,
        metadata: Mapping[str, Any] | None = None,
        warnings: Sequence[str] | None = None,
        artifact_id: str | None = None,
        data_ref: str | None = None,
    ) -> ChartArtifact:
        builder = ChartSpecBuilder(
            settings=self.settings,
            registry=self.registry,
            capability_catalog=self.capability_catalog,
        )
        return builder.build(
            request=request,
            data=data,
            context=context,
            metadata=metadata,
            warnings=warnings,
            artifact_id=artifact_id,
            data_ref=data_ref,
        )


def build_chart_data_slice(
    artifact: ChartArtifact,
    data: Sequence[Mapping[str, Any]] | NormalizedChartData,
    *,
    fields: Sequence[str] | None = None,
    filters: Mapping[str, Any] | None = None,
    max_rows: int | None = None,
    data_ref: str | None = None,
) -> ChartDataSlice:
    """Project one bounded deterministic data slice from chart data."""

    normalized = _coerce_normalized_data(data)
    resolved_fields = _resolve_fields(normalized=normalized, fields=fields)
    filtered_rows = _apply_filters(normalized.rows, filters)
    bounded_rows = filtered_rows[: _resolve_row_limit(max_rows)]
    projected_rows = [_project_row(row, resolved_fields) for row in bounded_rows]

    return ChartDataSlice(
        artifact_id=artifact.artifact_id,
        chart_type=artifact.chart_type,
        data_ref=data_ref or artifact.data_ref,
        fields=resolved_fields,
        rows=projected_rows,
        row_count=len(projected_rows),
        truncated=len(projected_rows) < len(filtered_rows),
        metadata={
            "matched_row_count": len(filtered_rows),
            "total_row_count": normalized.row_count,
        },
    )


def build_chart_computed_facts(
    artifact: ChartArtifact,
    data: Sequence[Mapping[str, Any]] | NormalizedChartData,
    *,
    filters: Mapping[str, Any] | None = None,
    value_fields: Sequence[str] | None = None,
    summary_text: str | None = None,
    data_ref: str | None = None,
) -> ChartComputedFacts:
    """Compute deterministic aggregate facts for exact follow-up answers."""

    normalized = _coerce_normalized_data(data)
    filtered_rows = _apply_filters(normalized.rows, filters)
    metric_fields = _resolve_metric_fields(
        artifact=artifact,
        normalized=normalized,
        requested_fields=value_fields,
    )
    aggregate_stats = _build_aggregate_stats(filtered_rows, metric_fields)
    extrema = _build_extrema(artifact=artifact, rows=filtered_rows, metric_fields=metric_fields)
    trend_summary = _build_trend_summary(
        artifact=artifact,
        rows=filtered_rows,
        metric_fields=metric_fields,
    )
    resolved_summary_text = summary_text or _build_facts_summary(
        artifact=artifact,
        row_count=len(filtered_rows),
        metric_fields=metric_fields,
    )

    return ChartComputedFacts(
        artifact_id=artifact.artifact_id,
        chart_type=artifact.chart_type,
        summary_text=resolved_summary_text,
        aggregate_stats=aggregate_stats,
        extrema=extrema,
        trend_summary=trend_summary,
        facts={
            "row_count": len(filtered_rows),
            "metric_fields": metric_fields,
            "available_fields": list(normalized.fields),
            "filters": dict(filters or {}),
        },
        data_ref=data_ref or artifact.data_ref,
        metadata={
            "matched_row_count": len(filtered_rows),
            "total_row_count": normalized.row_count,
        },
    )


def lookup_exact_chart_value(
    artifact: ChartArtifact,
    data: Sequence[Mapping[str, Any]] | NormalizedChartData,
    *,
    match_field: str,
    match_value: Any,
    value_field: str,
    series_field: str | None = None,
    series_value: Any | None = None,
    data_ref: str | None = None,
) -> ChartComputedFacts:
    """Look up one exact value without sending full rows through the LLM."""

    normalized = _coerce_normalized_data(data)
    resolved_match_field = validate_chart_field_name(match_field)
    resolved_value_field = validate_chart_field_name(value_field)
    resolved_series_field = validate_chart_field_name(series_field) if series_field else None
    _ensure_fields_exist(normalized, [resolved_match_field, resolved_value_field])
    if resolved_series_field is not None:
        _ensure_fields_exist(normalized, [resolved_series_field])
        if series_value is None:
            raise ChartDataValidationError("series_value is required when series_field is provided.")

    matched_rows = []
    for row in normalized.rows:
        if row.get(resolved_match_field) != match_value:
            continue
        if resolved_series_field is not None and row.get(resolved_series_field) != series_value:
            continue
        matched_rows.append(dict(row))

    if not matched_rows:
        return ChartComputedFacts(
            artifact_id=artifact.artifact_id,
            chart_type=artifact.chart_type,
            summary_text="No matching chart value was found.",
            facts={
                "matched": False,
                "match_field": resolved_match_field,
                "match_value": match_value,
                "value_field": resolved_value_field,
            },
            data_ref=data_ref or artifact.data_ref,
        )

    if len(matched_rows) > 1:
        raise ChartFollowupAmbiguousError(
            "The chart contains multiple matching rows. Please specify the series or filter more narrowly."
        )

    matched_row = matched_rows[0]
    value = matched_row.get(resolved_value_field)
    return ChartComputedFacts(
        artifact_id=artifact.artifact_id,
        chart_type=artifact.chart_type,
        summary_text="Computed one exact chart value.",
        aggregate_stats={resolved_value_field: {"count": 1, "total": value, "average": value}},
        facts={
            "matched": True,
            "match_field": resolved_match_field,
            "match_value": match_value,
            "value_field": resolved_value_field,
            "value": value,
            "row": matched_row,
        },
        data_ref=data_ref or artifact.data_ref,
    )


def filter_chart_data_by_period(
    artifact: ChartArtifact,
    data: Sequence[Mapping[str, Any]] | NormalizedChartData,
    *,
    field_name: str,
    start: str | date | datetime | time | None = None,
    end: str | date | datetime | time | None = None,
    fields: Sequence[str] | None = None,
    max_rows: int | None = None,
    data_ref: str | None = None,
) -> ChartDataSlice:
    """Filter chart rows by one inclusive temporal period."""

    normalized = _coerce_normalized_data(data)
    resolved_field_name = validate_chart_field_name(field_name)
    _ensure_fields_exist(normalized, [resolved_field_name])
    start_bound = _coerce_temporal_bound(start)
    end_bound = _coerce_temporal_bound(end)

    filtered_rows: list[dict[str, Any]] = []
    for row in normalized.rows:
        parsed_value = parse_temporal_value(row.get(resolved_field_name))
        if parsed_value is None:
            continue
        sort_key = temporal_sort_key(parsed_value)
        if start_bound is not None and sort_key < start_bound:
            continue
        if end_bound is not None and sort_key > end_bound:
            continue
        filtered_rows.append(dict(row))

    filtered_rows.sort(
        key=lambda row: temporal_sort_key(parse_temporal_value(row[resolved_field_name]))
    )
    return build_chart_data_slice(
        artifact,
        filtered_rows,
        fields=fields,
        max_rows=max_rows,
        data_ref=data_ref or artifact.data_ref,
    )


def compare_chart_series(
    artifact: ChartArtifact,
    data: Sequence[Mapping[str, Any]] | NormalizedChartData,
    *,
    series_field: str,
    left_series: Any,
    right_series: Any,
    value_field: str,
    x_field: str | None = None,
    data_ref: str | None = None,
) -> ChartComputedFacts:
    """Compare two series deterministically using totals and optional per-period deltas."""

    normalized = _coerce_normalized_data(data)
    resolved_series_field = validate_chart_field_name(series_field)
    resolved_value_field = validate_chart_field_name(value_field)
    resolved_x_field = validate_chart_field_name(x_field) if x_field else None
    required_fields = [resolved_series_field, resolved_value_field]
    if resolved_x_field is not None:
        required_fields.append(resolved_x_field)
    _ensure_fields_exist(normalized, required_fields)

    left_rows = [dict(row) for row in normalized.rows if row.get(resolved_series_field) == left_series]
    right_rows = [dict(row) for row in normalized.rows if row.get(resolved_series_field) == right_series]
    left_totals = _summarize_series(left_rows, resolved_value_field)
    right_totals = _summarize_series(right_rows, resolved_value_field)
    comparison: dict[str, Any] = {
        "series_field": resolved_series_field,
        "value_field": resolved_value_field,
        "left_series": left_series,
        "right_series": right_series,
        "left": left_totals,
        "right": right_totals,
        "difference": _stable_number(left_totals["total"] - right_totals["total"]),
        "ratio": _safe_ratio(left_totals["total"], right_totals["total"]),
    }
    if resolved_x_field is not None:
        comparison["by_x"] = _series_differences_by_x(
            rows=normalized.rows,
            x_field=resolved_x_field,
            series_field=resolved_series_field,
            value_field=resolved_value_field,
            left_series=left_series,
            right_series=right_series,
        )

    return ChartComputedFacts(
        artifact_id=artifact.artifact_id,
        chart_type=artifact.chart_type,
        summary_text=(
            f"Compared {left_series} to {right_series} using {resolved_value_field}."
        ),
        aggregate_stats={
            resolved_value_field: {
                "left_total": left_totals["total"],
                "right_total": right_totals["total"],
                "difference": comparison["difference"],
            }
        },
        facts=comparison,
        data_ref=data_ref or artifact.data_ref,
    )


def _coerce_normalized_data(
    data: Sequence[Mapping[str, Any]] | NormalizedChartData,
) -> NormalizedChartData:
    if isinstance(data, NormalizedChartData):
        return data
    return normalize_chart_data(data)


def _resolve_fields(
    *,
    normalized: NormalizedChartData,
    fields: Sequence[str] | None,
) -> list[str]:
    if not fields:
        return list(normalized.fields)

    resolved: list[str] = []
    seen: set[str] = set()
    for field_name in fields:
        normalized_field = validate_chart_field_name(field_name)
        if normalized_field not in normalized.field_profiles:
            raise ChartDataValidationError(
                f"The field '{normalized_field}' is not available in the chart data."
            )
        if normalized_field in seen:
            continue
        seen.add(normalized_field)
        resolved.append(normalized_field)
    return resolved


def _resolve_metric_fields(
    *,
    artifact: ChartArtifact,
    normalized: NormalizedChartData,
    requested_fields: Sequence[str] | None,
) -> list[str]:
    if requested_fields:
        resolved = _resolve_fields(normalized=normalized, fields=requested_fields)
        non_numeric = [field_name for field_name in resolved if normalized.profile_for(field_name).kind != "numeric"]
        if non_numeric:
            raise ChartDataValidationError(
                f"The fields {', '.join(non_numeric)} are not numeric and cannot be aggregated."
            )
        return resolved

    candidates: list[str] = []
    candidates.extend(_read_field_names(artifact.encoding, "y"))
    for key in ("value", "size"):
        field_name = _read_optional_field_name(artifact.encoding, key)
        if field_name is not None:
            candidates.append(field_name)
    if artifact.chart_type == "histogram":
        histogram_field = _read_optional_field_name(artifact.encoding, "x")
        if histogram_field is not None:
            candidates.append(histogram_field)

    resolved: list[str] = []
    seen: set[str] = set()
    for field_name in candidates:
        if field_name in normalized.field_profiles and normalized.profile_for(field_name).kind == "numeric":
            if field_name not in seen:
                resolved.append(field_name)
                seen.add(field_name)

    if resolved:
        return resolved

    return [
        field_name
        for field_name, profile in normalized.field_profiles.items()
        if profile.kind == "numeric"
    ]


def _apply_filters(
    rows: Sequence[Mapping[str, Any]],
    filters: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not filters:
        return [dict(row) for row in rows]

    resolved_filters = {
        validate_chart_field_name(field_name): expected
        for field_name, expected in filters.items()
    }
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if all(_matches_filter(row.get(field_name), expected) for field_name, expected in resolved_filters.items()):
            filtered.append(dict(row))
    return filtered


def _matches_filter(value: Any, expected: Any) -> bool:
    if isinstance(expected, _SEQUENCE_TYPES):
        return value in expected
    return value == expected


def _project_row(row: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    return {field_name: row.get(field_name) for field_name in fields}


def _resolve_row_limit(max_rows: int | None) -> int:
    if max_rows is None:
        return 10_000
    if max_rows < 1:
        raise ChartDataValidationError("max_rows must be greater than zero.")
    return max_rows


def _build_aggregate_stats(
    rows: Sequence[Mapping[str, Any]],
    metric_fields: Sequence[str],
) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for field_name in metric_fields:
        values = [numeric for row in rows if (numeric := _as_float(row.get(field_name))) is not None]
        if not values:
            continue
        total = sum(values)
        average = total / len(values)
        stats[field_name] = {
            "count": len(values),
            "total": _stable_number(total),
            "average": _stable_number(average),
        }
    return stats


def _build_extrema(
    *,
    artifact: ChartArtifact,
    rows: Sequence[Mapping[str, Any]],
    metric_fields: Sequence[str],
) -> dict[str, Any]:
    extrema: dict[str, Any] = {}
    identity_fields = _resolve_identity_fields(artifact=artifact, metric_fields=metric_fields, rows=rows)
    for field_name in metric_fields:
        values = [
            (row, numeric)
            for row in rows
            if (numeric := _as_float(row.get(field_name))) is not None
        ]
        if not values:
            continue
        minimum = min(values, key=lambda item: item[1])
        maximum = max(values, key=lambda item: item[1])
        extrema[field_name] = {
            "min": {
                "value": _stable_number(minimum[1]),
                "row": _row_identity(minimum[0], identity_fields),
            },
            "max": {
                "value": _stable_number(maximum[1]),
                "row": _row_identity(maximum[0], identity_fields),
            },
        }
    return extrema


def _build_trend_summary(
    *,
    artifact: ChartArtifact,
    rows: Sequence[Mapping[str, Any]],
    metric_fields: Sequence[str],
) -> dict[str, Any]:
    if not rows or not metric_fields:
        return {}

    time_field = _resolve_time_field(artifact=artifact, rows=rows)
    if time_field is None:
        return {}

    trend: dict[str, Any] = {"time_field": time_field}
    for field_name in metric_fields:
        series = []
        for row in rows:
            parsed_value = parse_temporal_value(row.get(time_field))
            numeric = _as_float(row.get(field_name))
            if parsed_value is None or numeric is None:
                continue
            series.append((temporal_sort_key(parsed_value), numeric))
        if len(series) < 2:
            continue
        series.sort(key=lambda item: item[0])
        first_value = series[0][1]
        last_value = series[-1][1]
        change = last_value - first_value
        direction = "flat"
        if change > 0:
            direction = "up"
        elif change < 0:
            direction = "down"
        trend[field_name] = {
            "direction": direction,
            "start": _stable_number(first_value),
            "end": _stable_number(last_value),
            "change": _stable_number(change),
            "percent_change": _safe_ratio(change, first_value, scale=100.0),
        }
    return trend


def _build_facts_summary(
    *,
    artifact: ChartArtifact,
    row_count: int,
    metric_fields: Sequence[str],
) -> str:
    if row_count == 0:
        return "No matching chart rows were found for the requested computation."
    if metric_fields:
        field_label = ", ".join(metric_fields)
        return f"Computed deterministic facts for {row_count} rows across {field_label}."
    return f"Computed deterministic facts for {row_count} chart rows from '{artifact.title}'."


def _resolve_identity_fields(
    *,
    artifact: ChartArtifact,
    metric_fields: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    fields: list[str] = []
    for key in ("x", "category", "task", "series", "time"):
        field_name = _read_optional_field_name(artifact.encoding, key)
        if field_name is not None and field_name not in fields:
            fields.append(field_name)
    if fields:
        return fields

    for row in rows:
        for field_name in row:
            if field_name not in metric_fields:
                fields.append(field_name)
        if fields:
            break
    return fields[:3]


def _row_identity(row: Mapping[str, Any], identity_fields: Sequence[str]) -> dict[str, Any]:
    if not identity_fields:
        return dict(row)
    return {field_name: row.get(field_name) for field_name in identity_fields}


def _resolve_time_field(
    *,
    artifact: ChartArtifact,
    rows: Sequence[Mapping[str, Any]],
) -> str | None:
    explicit_time = _read_optional_field_name(artifact.encoding, "time")
    if explicit_time is not None:
        return explicit_time

    for key in ("x", "category"):
        candidate = _read_optional_field_name(artifact.encoding, key)
        if candidate is None:
            continue
        if all(parse_temporal_value(row.get(candidate)) is not None for row in rows):
            return candidate
    return None


def _summarize_series(rows: Sequence[Mapping[str, Any]], value_field: str) -> dict[str, Any]:
    values = [numeric for row in rows if (numeric := _as_float(row.get(value_field))) is not None]
    if not values:
        return {"count": 0, "total": 0, "average": 0}
    total = sum(values)
    return {
        "count": len(values),
        "total": _stable_number(total),
        "average": _stable_number(total / len(values)),
    }


def _series_differences_by_x(
    *,
    rows: Sequence[Mapping[str, Any]],
    x_field: str,
    series_field: str,
    value_field: str,
    left_series: Any,
    right_series: Any,
) -> dict[str, Any]:
    by_x: dict[str, dict[str, float]] = {}
    for row in rows:
        series_name = row.get(series_field)
        if series_name not in {left_series, right_series}:
            continue
        numeric = _as_float(row.get(value_field))
        if numeric is None:
            continue
        x_value = str(row.get(x_field))
        bucket = by_x.setdefault(x_value, {str(left_series): 0.0, str(right_series): 0.0})
        bucket[str(series_name)] = bucket.get(str(series_name), 0.0) + numeric

    comparison: dict[str, Any] = {}
    left_key = str(left_series)
    right_key = str(right_series)
    for x_value, totals in by_x.items():
        left_total = totals.get(left_key, 0.0)
        right_total = totals.get(right_key, 0.0)
        comparison[x_value] = {
            left_key: _stable_number(left_total),
            right_key: _stable_number(right_total),
            "difference": _stable_number(left_total - right_total),
        }
    return comparison


def _read_optional_field_name(encoding: Mapping[str, Any], key: str) -> str | None:
    value = encoding.get(key)
    if isinstance(value, str) and value.strip():
        return validate_chart_field_name(value)
    return None


def _read_field_names(encoding: Mapping[str, Any], key: str) -> list[str]:
    value = encoding.get(key)
    if isinstance(value, str) and value.strip():
        return [validate_chart_field_name(value)]
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [validate_chart_field_name(item) for item in value]


def _ensure_fields_exist(normalized: NormalizedChartData, fields: Sequence[str]) -> None:
    missing = [field_name for field_name in fields if field_name not in normalized.field_profiles]
    if missing:
        raise ChartDataValidationError(
            f"The fields {', '.join(missing)} are not available in the chart data."
        )


def _coerce_temporal_bound(
    value: str | date | datetime | time | None,
) -> datetime | None:
    if value is None:
        return None
    parsed = parse_temporal_value(value)
    if parsed is None:
        raise ChartDataValidationError("Temporal filters must use ISO or month values.")
    return temporal_sort_key(parsed)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _stable_number(value: float | int) -> int | float:
    if isinstance(value, int):
        return value
    if float(value).is_integer():
        return int(value)
    return round(float(value), 6)


def _safe_ratio(numerator: float, denominator: float, *, scale: float = 1.0) -> float | None:
    if denominator == 0:
        return None
    return _stable_number((numerator / denominator) * scale)


__all__ = [
    "VisualizationComputationService",
    "build_chart_computed_facts",
    "build_chart_data_slice",
    "compare_chart_series",
    "filter_chart_data_by_period",
    "lookup_exact_chart_value",
]