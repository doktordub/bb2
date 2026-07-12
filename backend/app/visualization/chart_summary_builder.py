"""Deterministic builder for prompt-safe chart summaries and contributions."""

from __future__ import annotations

import math
import statistics
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.visualization.chart_data import (
    NormalizedChartData,
    count_unique_values,
    infer_time_range,
    normalize_chart_data,
    parse_temporal_value,
    temporal_sort_key,
    validate_chart_field_name,
)
from app.visualization.models import ChartArtifact, ChartContextSummary, ChartRequest, ContextContribution, VisualizationContext
from app.visualization.settings import VisualizationSettings
from app.visualization.validators import estimate_chart_summary_tokens, validate_chart_context_summary


@dataclass(frozen=True, slots=True)
class _SeriesSnapshot:
    name: str
    points: tuple[tuple[Any, float], ...]


@dataclass(slots=True)
class ChartSummaryBuilder:
    """Build bounded chart summaries and prompt context contributions."""

    settings: VisualizationSettings

    def build(
        self,
        *,
        request: ChartRequest,
        artifact: ChartArtifact,
        data: Sequence[Mapping[str, Any]] | NormalizedChartData,
        context: VisualizationContext,
        metadata: Mapping[str, Any] | None = None,
        warnings: Sequence[str] | None = None,
    ) -> ChartContextSummary:
        """Build one validated context-safe summary from a chart artifact and data."""

        normalized = data if isinstance(data, NormalizedChartData) else normalize_chart_data(data)
        analysis = _analyze_chart(artifact=artifact, normalized=normalized)
        summary = ChartContextSummary(
            artifact_id=artifact.artifact_id,
            chart_type=artifact.chart_type,
            title=artifact.title,
            description=artifact.description,
            renderer=artifact.renderer,
            data_source=request.data_source,
            x_field=analysis["x_field"],
            y_fields=analysis["y_fields"],
            series_field=analysis["series_field"],
            row_count=normalized.row_count,
            series_count=analysis["series_count"],
            category_count=analysis["category_count"],
            time_range=analysis["time_range"],
            summary_text=analysis["summary_text"],
            key_insights=list(analysis["key_insights"]),
            aggregate_stats=dict(analysis["aggregate_stats"]),
            extrema=dict(analysis["extrema"]),
            trend_summary=dict(analysis["trend_summary"]),
            warnings=_merge_text_values(artifact.warnings, normalized.warnings, warnings),
            data_ref=_resolve_summary_data_ref(
                artifact=artifact,
                context=context,
                settings=self.settings,
            ),
            metadata=_build_summary_metadata(
                artifact=artifact,
                context=context,
                metadata=metadata,
                allowlist=self.settings.safe_metadata_allowlist,
            ),
        )

        summary = _apply_summary_settings(summary=summary, settings=self.settings)
        summary = _compact_summary(summary=summary, settings=self.settings)
        summary = _assign_token_estimate(summary)
        return validate_chart_context_summary(summary, settings=self.settings)


def build_chart_context_contribution(summary: ChartContextSummary) -> ContextContribution:
    """Map one chart summary into the orchestration context contribution contract."""

    return ContextContribution(
        contribution_id=f"ctx_{summary.artifact_id}",
        kind="chart_summary",
        content=summary.model_dump(mode="python"),
        token_estimate=summary.token_estimate or estimate_chart_summary_tokens(summary),
        source_artifact_id=summary.artifact_id,
    )


def _apply_summary_settings(
    *,
    summary: ChartContextSummary,
    settings: VisualizationSettings,
) -> ChartContextSummary:
    aggregate_stats = summary.aggregate_stats if settings.context_summary.include_aggregate_stats else {}
    extrema = summary.extrema if settings.context_summary.include_extrema else {}
    trend_summary = summary.trend_summary if settings.context_summary.include_trend_summary else {}
    data_ref = summary.data_ref if settings.context_summary.include_data_ref or settings.artifact_store.exact_followup_retrieval_enabled else None
    return summary.model_copy(
        update={
            "aggregate_stats": aggregate_stats,
            "extrema": extrema,
            "trend_summary": trend_summary,
            "data_ref": data_ref,
        }
    )


def _compact_summary(
    *,
    summary: ChartContextSummary,
    settings: VisualizationSettings,
) -> ChartContextSummary:
    token_limit = min(
        settings.context_summary.max_tokens_per_chart_summary,
        settings.context_summary.max_total_visualization_context_tokens,
    )

    candidate = _assign_token_estimate(summary)
    if (candidate.token_estimate or 0) <= token_limit:
        return candidate

    compacted = candidate.model_copy(update={"description": None})
    compacted = _assign_token_estimate(compacted)
    if (compacted.token_estimate or 0) <= token_limit:
        return compacted

    compacted = compacted.model_copy(
        update={
            "summary_text": _compact_summary_text(compacted.summary_text, compacted.key_insights),
            "trend_summary": _compact_mapping(compacted.trend_summary, limit=2),
            "aggregate_stats": _prioritize_aggregate_stats(compacted.aggregate_stats),
            "extrema": _compact_mapping(compacted.extrema, limit=3),
            "warnings": compacted.warnings[:3],
        }
    )
    compacted = _assign_token_estimate(compacted)
    if (compacted.token_estimate or 0) <= token_limit:
        return compacted

    compacted = compacted.model_copy(
        update={
            "key_insights": compacted.key_insights[:2],
            "summary_text": _compact_summary_text(compacted.summary_text, compacted.key_insights[:2]),
            "time_range": _compact_time_range(compacted.time_range),
            "trend_summary": {},
        }
    )
    compacted = _assign_token_estimate(compacted)
    if (compacted.token_estimate or 0) <= token_limit:
        return compacted

    compacted = _assign_token_estimate(
        compacted.model_copy(
            update={
                "key_insights": compacted.key_insights[:1],
                "aggregate_stats": _prioritize_aggregate_stats(compacted.aggregate_stats, limit=3),
                "extrema": _compact_mapping(compacted.extrema, limit=2),
                "summary_text": _compact_summary_text(compacted.summary_text, compacted.key_insights[:1], max_words=36),
            }
        )
    )
    if (compacted.token_estimate or 0) <= token_limit:
        return compacted

    minimal_summary_text = f"{summary.chart_type.replace('_', ' ')} chart, {summary.row_count} rows."
    return _assign_token_estimate(
        compacted.model_copy(
            update={
                "description": None,
                "time_range": None,
                "key_insights": [],
                "aggregate_stats": {},
                "extrema": {},
                "trend_summary": {},
                "warnings": [],
                "metadata": {},
                "summary_text": minimal_summary_text,
            }
        )
    )


def _assign_token_estimate(summary: ChartContextSummary) -> ChartContextSummary:
    estimated = summary.model_copy(update={"token_estimate": None})
    estimate = estimate_chart_summary_tokens(estimated)
    stable = estimated.model_copy(update={"token_estimate": estimate})
    final_estimate = estimate_chart_summary_tokens(stable.model_copy(update={"token_estimate": None}))
    return stable.model_copy(update={"token_estimate": max(estimate, final_estimate)})


def _analyze_chart(
    *,
    artifact: ChartArtifact,
    normalized: NormalizedChartData,
) -> dict[str, Any]:
    chart_type = artifact.chart_type
    if chart_type in {"bar", "grouped_bar", "stacked_bar", "horizontal_bar"}:
        return _summarize_bar_family(artifact=artifact, normalized=normalized, label_noun="category")
    if chart_type in {"line", "multi_line", "area"}:
        return _summarize_line_family(artifact=artifact, normalized=normalized)
    if chart_type in {"pie", "donut", "treemap"}:
        return _summarize_part_to_whole(artifact=artifact, normalized=normalized)
    if chart_type in {"scatter", "bubble"}:
        return _summarize_scatter_family(artifact=artifact, normalized=normalized)
    if chart_type == "histogram":
        return _summarize_histogram(artifact=artifact, normalized=normalized)
    if chart_type == "box_plot":
        return _summarize_box_plot(artifact=artifact, normalized=normalized)
    if chart_type == "heatmap":
        return _summarize_heatmap(artifact=artifact, normalized=normalized)
    if chart_type == "waterfall":
        return _summarize_waterfall(artifact=artifact, normalized=normalized)
    if chart_type == "gantt":
        return _summarize_gantt(artifact=artifact, normalized=normalized)
    if chart_type == "radar":
        return _summarize_bar_family(artifact=artifact, normalized=normalized, label_noun="dimension")
    if chart_type == "table":
        return _summarize_table(artifact=artifact, normalized=normalized)
    return _summarize_table(artifact=artifact, normalized=normalized)


def _summarize_bar_family(
    *,
    artifact: ChartArtifact,
    normalized: NormalizedChartData,
    label_noun: str,
) -> dict[str, Any]:
    label_field = _primary_label_field(artifact, normalized)
    y_fields = _numeric_identity_fields(artifact, normalized)
    series = _extract_series(artifact=artifact, normalized=normalized)
    category_totals = OrderedDict[str, float]()
    for row in normalized.rows:
        label = _format_label(row.get(label_field))
        category_totals[label] = category_totals.get(label, 0.0) + sum(
            float(row.get(field_name) or 0) for field_name in y_fields
        )
    top_label, top_total = max(category_totals.items(), key=lambda item: item[1])
    bottom_label, bottom_total = min(category_totals.items(), key=lambda item: item[1])

    aggregate_stats: dict[str, Any] = {
        "combined_total": _round_number(sum(category_totals.values())),
    }
    extrema: dict[str, Any] = {
        f"top_{label_noun}": {label_noun: top_label, "value": _round_number(top_total)},
        f"bottom_{label_noun}": {label_noun: bottom_label, "value": _round_number(bottom_total)},
        "series_extrema": {},
    }

    for snapshot in series:
        values = [point[1] for point in snapshot.points]
        aggregate_stats[f"{snapshot.name}_total"] = _round_number(sum(values))
        aggregate_stats[f"average_{snapshot.name}"] = _round_number(statistics.fmean(values))
        highest_label, highest_value = max(snapshot.points, key=lambda item: item[1])
        lowest_label, lowest_value = min(snapshot.points, key=lambda item: item[1])
        extrema["series_extrema"][snapshot.name] = {
            "highest": {label_noun: _format_label(highest_label), "value": _round_number(highest_value)},
            "lowest": {label_noun: _format_label(lowest_label), "value": _round_number(lowest_value)},
        }

    key_insights = [
        f"Top {label_noun} was {top_label} at {_format_number(top_total)}.",
        f"Lowest {label_noun} was {bottom_label} at {_format_number(bottom_total)}.",
    ]
    if len(series) > 1:
        strongest_series = max(series, key=lambda snapshot: sum(point[1] for point in snapshot.points))
        key_insights.append(
            f"Series {strongest_series.name} has the largest total at {_format_number(sum(point[1] for point in strongest_series.points))}."
        )
    else:
        only_series = series[0]
        key_insights.append(
            f"Series {only_series.name} averages {_format_number(statistics.fmean(point[1] for point in only_series.points))} per {label_noun}."
        )

    summary_text = (
        f"{artifact.chart_type.replace('_', ' ').capitalize()} chart across {len(category_totals)} {label_noun}s "
        f"and {len(series)} series. Top {label_noun} was {top_label} at {_format_number(top_total)}. "
        f"Combined total was {_format_number(sum(category_totals.values()))}."
    )

    return {
        "x_field": label_field,
        "y_fields": list(y_fields),
        "series_field": _series_field(artifact),
        "series_count": len(series),
        "category_count": len(category_totals),
        "time_range": infer_time_range(normalized.rows, field_name=_time_field(artifact, normalized)),
        "summary_text": summary_text,
        "key_insights": key_insights[:3],
        "aggregate_stats": aggregate_stats,
        "extrema": extrema,
        "trend_summary": {},
    }


def _summarize_line_family(*, artifact: ChartArtifact, normalized: NormalizedChartData) -> dict[str, Any]:
    time_field = _time_field(artifact, normalized) or _primary_label_field(artifact, normalized)
    series = _extract_series(artifact=artifact, normalized=normalized)
    aggregate_stats: dict[str, Any] = {}
    extrema: dict[str, Any] = {}
    trend_summary: dict[str, Any] = {}
    key_insights: list[str] = []

    for snapshot in series:
        first_label, first_value = snapshot.points[0]
        last_label, last_value = snapshot.points[-1]
        highest_label, highest_value = max(snapshot.points, key=lambda item: item[1])
        lowest_label, lowest_value = min(snapshot.points, key=lambda item: item[1])
        largest_change = _largest_change(snapshot.points)
        direction = _direction(last_value - first_value)
        aggregate_stats[f"{snapshot.name}_start"] = _round_number(first_value)
        aggregate_stats[f"{snapshot.name}_end"] = _round_number(last_value)
        aggregate_stats[f"{snapshot.name}_change"] = _round_number(last_value - first_value)
        aggregate_stats[f"average_{snapshot.name}"] = _round_number(statistics.fmean(point[1] for point in snapshot.points))
        extrema[snapshot.name] = {
            "peak": {"x": _format_label(highest_label), "value": _round_number(highest_value)},
            "trough": {"x": _format_label(lowest_label), "value": _round_number(lowest_value)},
        }
        trend_summary[snapshot.name] = {
            "direction": direction,
            "largest_change": {
                "from": _format_label(largest_change[0]),
                "to": _format_label(largest_change[1]),
                "delta": _round_number(largest_change[2]),
            },
        }
        key_insights.append(
            f"{snapshot.name} moved {direction} from {_format_number(first_value)} to {_format_number(last_value)}."
        )
        key_insights.append(
            f"{snapshot.name} peaked at {_format_number(highest_value)} on {_format_label(highest_label)}."
        )

    summary_text = (
        f"{artifact.chart_type.replace('_', ' ').capitalize()} chart covering {len(series[0].points)} time points "
        f"across {len(series)} series. {key_insights[0]}"
    )

    return {
        "x_field": _primary_label_field(artifact, normalized),
        "y_fields": list(_numeric_identity_fields(artifact, normalized)),
        "series_field": _series_field(artifact),
        "series_count": len(series),
        "category_count": count_unique_values(normalized.rows, _primary_label_field(artifact, normalized)),
        "time_range": infer_time_range(normalized.rows, field_name=time_field),
        "summary_text": summary_text,
        "key_insights": _dedupe_strings(key_insights)[:3],
        "aggregate_stats": aggregate_stats,
        "extrema": extrema,
        "trend_summary": trend_summary,
    }


def _summarize_part_to_whole(*, artifact: ChartArtifact, normalized: NormalizedChartData) -> dict[str, Any]:
    category_field = _primary_label_field(artifact, normalized)
    value_field = _numeric_identity_fields(artifact, normalized)[0]
    pairs = [(_format_label(row.get(category_field)), float(row.get(value_field) or 0)) for row in normalized.rows]
    total = sum(value for _, value in pairs)
    largest_label, largest_value = max(pairs, key=lambda item: item[1])
    smallest_label, smallest_value = min(pairs, key=lambda item: item[1])
    top_two_share = 0.0 if not pairs else sum(value for _, value in sorted(pairs, key=lambda item: item[1], reverse=True)[:2]) / total

    return {
        "x_field": category_field,
        "y_fields": [value_field],
        "series_field": None,
        "series_count": 1,
        "category_count": len(pairs),
        "time_range": None,
        "summary_text": (
            f"{artifact.chart_type.replace('_', ' ').capitalize()} chart across {len(pairs)} categories. "
            f"{largest_label} leads at {_format_number(largest_value)}, or {_format_percent(largest_value / total)} of the total."
        ),
        "key_insights": [
            f"Largest category is {largest_label} at {_format_percent(largest_value / total)} of the total.",
            f"Smallest category is {smallest_label} at {_format_percent(smallest_value / total)} of the total.",
            f"The top two categories account for {_format_percent(top_two_share)} of the total.",
        ],
        "aggregate_stats": {
            "total": _round_number(total),
            "average": _round_number(statistics.fmean(value for _, value in pairs)),
        },
        "extrema": {
            "largest_category": {"category": largest_label, "value": _round_number(largest_value)},
            "smallest_category": {"category": smallest_label, "value": _round_number(smallest_value)},
        },
        "trend_summary": {"concentration": _format_percent(top_two_share)},
    }


def _summarize_scatter_family(*, artifact: ChartArtifact, normalized: NormalizedChartData) -> dict[str, Any]:
    x_field = _required_encoding_field(artifact, "x")
    y_field = _required_scalar_encoding_field(artifact, "y")
    size_field = _optional_encoding_field(artifact, "size")
    x_values = [float(row.get(x_field) or 0) for row in normalized.rows]
    y_values = [float(row.get(y_field) or 0) for row in normalized.rows]
    correlation = _pearson_correlation(x_values, y_values)
    relationship = _relationship_label(correlation)
    outlier_count = _scatter_outlier_count(x_values=x_values, y_values=y_values)

    aggregate_stats = {
        "x_min": _round_number(min(x_values)),
        "x_max": _round_number(max(x_values)),
        "y_min": _round_number(min(y_values)),
        "y_max": _round_number(max(y_values)),
    }
    if correlation is not None:
        aggregate_stats["correlation"] = _round_number(correlation)
    if size_field is not None:
        sizes = [float(row.get(size_field) or 0) for row in normalized.rows]
        aggregate_stats["size_total"] = _round_number(sum(sizes))

    return {
        "x_field": x_field,
        "y_fields": [y_field],
        "series_field": size_field,
        "series_count": 1,
        "category_count": None,
        "time_range": None,
        "summary_text": (
            f"{artifact.chart_type.replace('_', ' ').capitalize()} chart with {len(x_values)} points. "
            f"The relationship is {relationship} with x values from {_format_number(min(x_values))} to {_format_number(max(x_values))}."
        ),
        "key_insights": [
            f"The x range runs from {_format_number(min(x_values))} to {_format_number(max(x_values))}.",
            f"The y range runs from {_format_number(min(y_values))} to {_format_number(max(y_values))}.",
            f"Outlier hint count is {outlier_count} and the overall relationship is {relationship}.",
        ],
        "aggregate_stats": aggregate_stats,
        "extrema": {
            "highest_x": _point_extreme(normalized=normalized, field_name=x_field),
            "highest_y": _point_extreme(normalized=normalized, field_name=y_field),
        },
        "trend_summary": {
            "relationship": relationship,
            "correlation": _round_number(correlation) if correlation is not None else None,
            "outlier_count": outlier_count,
        },
    }


def _summarize_histogram(*, artifact: ChartArtifact, normalized: NormalizedChartData) -> dict[str, Any]:
    value_field = _primary_label_field(artifact, normalized)
    values = sorted(float(row.get(value_field) or 0) for row in normalized.rows)
    bins = _histogram_bins(values)
    modal_bin = max(bins, key=lambda item: item[2])
    shape_hint = _histogram_shape(values)

    return {
        "x_field": value_field,
        "y_fields": [value_field],
        "series_field": None,
        "series_count": 1,
        "category_count": len(bins),
        "time_range": None,
        "summary_text": (
            f"Histogram across {len(values)} observations with {len(bins)} bins. "
            f"The modal bin spans {_format_number(modal_bin[0])} to {_format_number(modal_bin[1])}."
        ),
        "key_insights": [
            f"The observed range is {_format_number(values[0])} to {_format_number(values[-1])}.",
            f"The modal bin covers {_format_number(modal_bin[0])} to {_format_number(modal_bin[1])} with {modal_bin[2]} values.",
            f"The overall distribution looks {shape_hint}.",
        ],
        "aggregate_stats": {
            "bin_count": len(bins),
            "minimum": _round_number(values[0]),
            "maximum": _round_number(values[-1]),
            "average": _round_number(statistics.fmean(values)),
            "median": _round_number(statistics.median(values)),
        },
        "extrema": {
            "modal_bin": {"start": _round_number(modal_bin[0]), "end": _round_number(modal_bin[1]), "count": modal_bin[2]}
        },
        "trend_summary": {"shape": shape_hint},
    }


def _summarize_box_plot(*, artifact: ChartArtifact, normalized: NormalizedChartData) -> dict[str, Any]:
    x_field = _primary_label_field(artifact, normalized)
    value_field = _numeric_identity_fields(artifact, normalized)[0]
    values = sorted(float(row.get(value_field) or 0) for row in normalized.rows)
    q1, median, q3 = _quartiles(values)
    iqr = q3 - q1
    lower_bound = q1 - (1.5 * iqr)
    upper_bound = q3 + (1.5 * iqr)
    non_outliers = [value for value in values if lower_bound <= value <= upper_bound]
    outlier_count = len(values) - len(non_outliers)

    return {
        "x_field": x_field,
        "y_fields": [value_field],
        "series_field": None,
        "series_count": 1,
        "category_count": count_unique_values(normalized.rows, x_field),
        "time_range": None,
        "summary_text": (
            f"Box plot across {count_unique_values(normalized.rows, x_field)} categories. "
            f"Median is {_format_number(median)} and {_format_number(outlier_count)} observations fall outside the whiskers."
        ),
        "key_insights": [
            f"Median is {_format_number(median)} with quartiles at {_format_number(q1)} and {_format_number(q3)}.",
            f"Whiskers extend from {_format_number(min(non_outliers))} to {_format_number(max(non_outliers))}.",
            f"Outlier count is {outlier_count}.",
        ],
        "aggregate_stats": {
            "minimum": _round_number(values[0]),
            "q1": _round_number(q1),
            "median": _round_number(median),
            "q3": _round_number(q3),
            "maximum": _round_number(values[-1]),
        },
        "extrema": {
            "whiskers": {"low": _round_number(min(non_outliers)), "high": _round_number(max(non_outliers))},
            "outlier_count": outlier_count,
        },
        "trend_summary": {"spread": _round_number(iqr)},
    }


def _summarize_heatmap(*, artifact: ChartArtifact, normalized: NormalizedChartData) -> dict[str, Any]:
    x_field = _required_encoding_field(artifact, "x")
    y_field = _required_scalar_encoding_field(artifact, "y")
    value_field = _required_encoding_field(artifact, "value")
    cells = [
        {
            "x": _format_label(row.get(x_field)),
            "y": _format_label(row.get(y_field)),
            "value": float(row.get(value_field) or 0),
        }
        for row in normalized.rows
    ]
    hottest = max(cells, key=lambda cell: cell["value"])
    coldest = min(cells, key=lambda cell: cell["value"])
    x_totals = OrderedDict[str, float]()
    y_totals = OrderedDict[str, float]()
    for cell in cells:
        x_totals[cell["x"]] = x_totals.get(cell["x"], 0.0) + cell["value"]
        y_totals[cell["y"]] = y_totals.get(cell["y"], 0.0) + cell["value"]
    strongest_x = max(x_totals.items(), key=lambda item: item[1])
    strongest_y = max(y_totals.items(), key=lambda item: item[1])

    return {
        "x_field": x_field,
        "y_fields": [value_field],
        "series_field": y_field,
        "series_count": count_unique_values(normalized.rows, y_field),
        "category_count": count_unique_values(normalized.rows, x_field),
        "time_range": infer_time_range(normalized.rows, field_name=_time_field(artifact, normalized)),
        "summary_text": (
            f"Heatmap across {len(x_totals)} x categories and {len(y_totals)} y categories. "
            f"The highest cell is {hottest['x']} / {hottest['y']} at {_format_number(hottest['value'])}."
        ),
        "key_insights": [
            f"The highest cell is {hottest['x']} / {hottest['y']} at {_format_number(hottest['value'])}.",
            f"The lowest cell is {coldest['x']} / {coldest['y']} at {_format_number(coldest['value'])}.",
            f"Strongest x category is {strongest_x[0]} and strongest y category is {strongest_y[0]}.",
        ],
        "aggregate_stats": {
            "total": _round_number(sum(cell["value"] for cell in cells)),
            "average": _round_number(statistics.fmean(cell["value"] for cell in cells)),
            "x_category_count": len(x_totals),
            "y_category_count": len(y_totals),
        },
        "extrema": {
            "highest_cell": hottest,
            "lowest_cell": coldest,
        },
        "trend_summary": {
            "strongest_x": {"category": strongest_x[0], "value": _round_number(strongest_x[1])},
            "strongest_y": {"category": strongest_y[0], "value": _round_number(strongest_y[1])},
        },
    }


def _summarize_waterfall(*, artifact: ChartArtifact, normalized: NormalizedChartData) -> dict[str, Any]:
    category_field = _primary_label_field(artifact, normalized)
    value_field = _numeric_identity_fields(artifact, normalized)[0]
    steps = [(_format_label(row.get(category_field)), float(row.get(value_field) or 0)) for row in normalized.rows]
    cumulative: list[tuple[str, float]] = []
    running_total = 0.0
    for label, value in steps:
        running_total += value
        cumulative.append((label, running_total))
    largest_positive = max(steps, key=lambda item: item[1])
    largest_negative = min(steps, key=lambda item: item[1])

    return {
        "x_field": category_field,
        "y_fields": [value_field],
        "series_field": None,
        "series_count": 1,
        "category_count": len(steps),
        "time_range": None,
        "summary_text": (
            f"Waterfall chart with {len(steps)} steps. The cumulative total ends at {_format_number(cumulative[-1][1])} "
            f"after a starting contribution of {_format_number(steps[0][1])}."
        ),
        "key_insights": [
            f"Final cumulative value is {_format_number(cumulative[-1][1])}.",
            f"Largest positive contribution is {largest_positive[0]} at {_format_number(largest_positive[1])}.",
            f"Largest negative contribution is {largest_negative[0]} at {_format_number(largest_negative[1])}.",
        ],
        "aggregate_stats": {
            "start_value": _round_number(steps[0][1]),
            "end_value": _round_number(cumulative[-1][1]),
            "total_change": _round_number(sum(value for _, value in steps)),
        },
        "extrema": {
            "largest_positive": {"category": largest_positive[0], "value": _round_number(largest_positive[1])},
            "largest_negative": {"category": largest_negative[0], "value": _round_number(largest_negative[1])},
        },
        "trend_summary": {"net_direction": _direction(cumulative[-1][1] - steps[0][1])},
    }


def _summarize_gantt(*, artifact: ChartArtifact, normalized: NormalizedChartData) -> dict[str, Any]:
    task_field = _required_encoding_field(artifact, "task")
    start_field = _required_encoding_field(artifact, "start")
    end_field = _required_encoding_field(artifact, "end")
    durations: list[tuple[str, float]] = []
    for row in normalized.rows:
        start_value = parse_temporal_value(row.get(start_field))
        end_value = parse_temporal_value(row.get(end_field))
        if start_value is None or end_value is None:
            continue
        duration_days = max(
            0.0,
            (temporal_sort_key(end_value) - temporal_sort_key(start_value)).total_seconds() / 86400,
        )
        durations.append((_format_label(row.get(task_field)), duration_days))
    longest_task = max(durations, key=lambda item: item[1])
    shortest_task = min(durations, key=lambda item: item[1])
    time_range = infer_time_range(normalized.rows, start_field=start_field, end_field=end_field)
    schedule_span = 0.0
    if time_range is not None:
        start_time = parse_temporal_value(time_range["start"])
        end_time = parse_temporal_value(time_range["end"])
        if start_time is not None and end_time is not None:
            schedule_span = (temporal_sort_key(end_time) - temporal_sort_key(start_time)).total_seconds() / 86400

    return {
        "x_field": task_field,
        "y_fields": [],
        "series_field": None,
        "series_count": 1,
        "category_count": len(durations),
        "time_range": time_range,
        "summary_text": (
            f"Gantt chart spanning {len(durations)} tasks from {time_range['start'] if time_range else 'unknown'} "
            f"to {time_range['end'] if time_range else 'unknown'}. Longest task is {longest_task[0]}."
        ),
        "key_insights": [
            f"Schedule spans {_format_number(schedule_span)} days across {len(durations)} tasks.",
            f"Longest task is {longest_task[0]} at {_format_number(longest_task[1])} days.",
            f"Shortest task is {shortest_task[0]} at {_format_number(shortest_task[1])} days.",
        ],
        "aggregate_stats": {
            "task_count": len(durations),
            "schedule_span_days": _round_number(schedule_span),
            "average_task_duration_days": _round_number(statistics.fmean(duration for _, duration in durations)),
        },
        "extrema": {
            "longest_task": {"task": longest_task[0], "duration_days": _round_number(longest_task[1])},
            "shortest_task": {"task": shortest_task[0], "duration_days": _round_number(shortest_task[1])},
        },
        "trend_summary": {"longest_task": longest_task[0]},
    }


def _summarize_table(*, artifact: ChartArtifact, normalized: NormalizedChartData) -> dict[str, Any]:
    numeric_fields = [
        profile.name
        for profile in normalized.field_profiles.values()
        if profile.kind == "numeric"
    ]
    aggregate_stats: dict[str, Any] = {
        "column_count": len(normalized.fields),
        "row_count": normalized.row_count,
    }
    extrema: dict[str, Any] = {}
    for field_name in numeric_fields[:3]:
        values = [float(row.get(field_name) or 0) for row in normalized.rows]
        aggregate_stats[f"{field_name}_total"] = _round_number(sum(values))
        aggregate_stats[f"average_{field_name}"] = _round_number(statistics.fmean(values))
        max_row = max(normalized.rows, key=lambda row: float(row.get(field_name) or 0))
        extrema[field_name] = {
            "value": _round_number(float(max_row.get(field_name) or 0)),
            "row": {field_name: _round_number(float(max_row.get(field_name) or 0))},
        }

    x_field = normalized.fields[0] if normalized.fields else None
    y_fields = numeric_fields[:3]
    first_numeric_field = numeric_fields[0] if numeric_fields else None
    summary_text = f"Table with {normalized.row_count} rows and {len(normalized.fields)} columns."
    if first_numeric_field is not None:
        summary_text += (
            f" {first_numeric_field} totals {_format_number(aggregate_stats[f'{first_numeric_field}_total'])}."
        )

    key_insights = [
        f"The table has {normalized.row_count} rows and {len(normalized.fields)} columns.",
        f"Numeric columns detected: {', '.join(y_fields) if y_fields else 'none'}.",
    ]
    if first_numeric_field is not None:
        key_insights.append(
            f"{first_numeric_field} totals {_format_number(aggregate_stats[f'{first_numeric_field}_total'])}."
        )
    else:
        key_insights.append("The table contains no numeric aggregates.")

    return {
        "x_field": x_field,
        "y_fields": y_fields,
        "series_field": None,
        "series_count": max(1, len(y_fields)) if normalized.row_count else 0,
        "category_count": None,
        "time_range": infer_time_range(normalized.rows, field_name=x_field) if x_field else None,
        "summary_text": summary_text,
        "key_insights": key_insights[:3],
        "aggregate_stats": aggregate_stats,
        "extrema": extrema,
        "trend_summary": {},
    }


def _extract_series(
    *,
    artifact: ChartArtifact,
    normalized: NormalizedChartData,
) -> tuple[_SeriesSnapshot, ...]:
    label_field = _primary_label_field(artifact, normalized)
    y_fields = _encoding_field_names(artifact, "y")
    if y_fields:
        return tuple(
            _SeriesSnapshot(
                name=field_name,
                points=tuple(
                    (_label_value(row, label_field), float(row.get(field_name) or 0))
                    for row in normalized.rows
                ),
            )
            for field_name in y_fields
        )

    series_field = _series_field(artifact)
    value_field = _optional_encoding_field(artifact, "value")
    if series_field is not None and value_field is not None:
        grouped: OrderedDict[str, list[tuple[Any, float]]] = OrderedDict()
        for row in normalized.rows:
            grouped.setdefault(_format_label(row.get(series_field)), []).append(
                (_label_value(row, label_field), float(row.get(value_field) or 0))
            )
        return tuple(
            _SeriesSnapshot(name=series_name, points=tuple(points))
            for series_name, points in grouped.items()
        )

    value_fields = _numeric_identity_fields(artifact, normalized)
    if not value_fields:
        return (_SeriesSnapshot(name="values", points=tuple()),)
    field_name = value_fields[0]
    return (
        _SeriesSnapshot(
            name=field_name,
            points=tuple(
                (_label_value(row, label_field), float(row.get(field_name) or 0))
                for row in normalized.rows
            ),
        ),
    )


def _numeric_identity_fields(artifact: ChartArtifact, normalized: NormalizedChartData) -> tuple[str, ...]:
    y_fields = _encoding_field_names(artifact, "y")
    if y_fields:
        return y_fields
    value_field = _optional_encoding_field(artifact, "value")
    if value_field is not None:
        return (value_field,)
    if artifact.chart_type == "histogram":
        return (_primary_label_field(artifact, normalized),)
    if artifact.chart_type == "table":
        return tuple(
            profile.name
            for profile in normalized.field_profiles.values()
            if profile.kind == "numeric"
        )
    return ()


def _primary_label_field(artifact: ChartArtifact, normalized: NormalizedChartData) -> str:
    for key in ("x", "category", "dimension", "task"):
        field_name = _optional_encoding_field(artifact, key)
        if field_name is not None:
            return field_name
    if normalized.fields:
        return normalized.fields[0]
    raise ValueError("Expected at least one field in normalized chart data.")


def _time_field(artifact: ChartArtifact, normalized: NormalizedChartData) -> str | None:
    explicit_time = _optional_encoding_field(artifact, "time")
    if explicit_time is not None:
        return explicit_time
    candidate = _primary_label_field(artifact, normalized)
    profile = normalized.field_profiles.get(candidate)
    if profile is not None and profile.kind == "temporal":
        return candidate
    return None


def _series_field(artifact: ChartArtifact) -> str | None:
    if artifact.chart_type == "heatmap":
        return _optional_encoding_field(artifact, "y")
    return _optional_encoding_field(artifact, "series")


def _required_encoding_field(artifact: ChartArtifact, key: str) -> str:
    value = _optional_encoding_field(artifact, key)
    if value is None:
        raise ValueError(f"Expected encoding field '{key}'.")
    return value


def _required_scalar_encoding_field(artifact: ChartArtifact, key: str) -> str:
    values = _encoding_field_names(artifact, key)
    if len(values) != 1:
        raise ValueError(f"Expected exactly one '{key}' field.")
    return values[0]


def _optional_encoding_field(artifact: ChartArtifact, key: str) -> str | None:
    value = artifact.encoding.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return validate_chart_field_name(value)
    return None


def _encoding_field_names(artifact: ChartArtifact, key: str) -> tuple[str, ...]:
    value = artifact.encoding.get(key)
    if value is None:
        return ()
    if isinstance(value, str):
        return (validate_chart_field_name(value),)
    if isinstance(value, Sequence):
        return tuple(validate_chart_field_name(item) for item in value)
    return ()


def _build_summary_metadata(
    *,
    artifact: ChartArtifact,
    context: VisualizationContext,
    metadata: Mapping[str, Any] | None,
    allowlist: Sequence[str],
) -> dict[str, Any]:
    normalized: dict[str, Any] = {"source_agent": context.agent_name}
    allowed_keys = set(allowlist)

    for key, value in artifact.metadata.items():
        normalized_key = validate_chart_field_name(key)
        if normalized_key == "source":
            continue
        if normalized_key in allowed_keys:
            normalized[normalized_key] = value

    if metadata is not None:
        for key, value in metadata.items():
            normalized_key = validate_chart_field_name(key)
            if normalized_key in allowed_keys:
                normalized[normalized_key] = value
    return normalized


def _resolve_summary_data_ref(
    *,
    artifact: ChartArtifact,
    context: VisualizationContext,
    settings: VisualizationSettings,
) -> str | None:
    if artifact.data_ref is not None:
        return artifact.data_ref
    if settings.context_summary.include_data_ref or settings.artifact_store.exact_followup_retrieval_enabled:
        return f"artifact://{context.session_id}/{artifact.artifact_id}"
    return None


def _merge_text_values(*value_groups: Sequence[str] | None) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for group in value_groups:
        if group is None:
            continue
        for value in group:
            text = str(value).strip()
            if text and text not in seen:
                values.append(text)
                seen.add(text)
    return values[:8]


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    return _merge_text_values(values)


def _compact_mapping(payload: Mapping[str, Any], *, limit: int) -> dict[str, Any]:
    return {key: payload[key] for key in list(payload.keys())[:limit]}


def _prioritize_aggregate_stats(payload: Mapping[str, Any], *, limit: int = 5) -> dict[str, Any]:
    preferred_order = [key for key in payload if key.endswith("_total") or key in {"total", "combined_total", "row_count", "column_count"}]
    remaining = [key for key in payload if key not in preferred_order]
    ordered_keys = preferred_order + remaining
    return {key: payload[key] for key in ordered_keys[:limit]}


def _compact_time_range(time_range: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if time_range is None:
        return None
    return {key: value for key, value in time_range.items() if key in {"start", "end"}}


def _compact_summary_text(summary_text: str, key_insights: Sequence[str], *, max_words: int = 48) -> str:
    if key_insights:
        candidate = " ".join(key_insights)
    else:
        candidate = summary_text
    words = candidate.split()
    if len(words) <= max_words:
        return candidate
    return " ".join(words[:max_words]).rstrip(".,") + "."


def _label_value(row: Mapping[str, Any], label_field: str) -> Any:
    return row.get(label_field)


def _largest_change(points: Sequence[tuple[Any, float]]) -> tuple[Any, Any, float]:
    pairs = zip(points, points[1:], strict=False)
    largest = None
    for current, following in pairs:
        delta = following[1] - current[1]
        if largest is None or abs(delta) > abs(largest[2]):
            largest = (current[0], following[0], delta)
    if largest is None:
        point = points[0]
        return (point[0], point[0], 0.0)
    return largest


def _histogram_bins(values: Sequence[float]) -> list[tuple[float, float, int]]:
    if len(values) == 1 or values[0] == values[-1]:
        return [(values[0], values[-1], len(values))]
    bin_count = max(1, min(12, math.ceil(math.sqrt(len(values)))))
    span = values[-1] - values[0]
    width = span / bin_count
    bins = [(values[0] + (index * width), values[0] + ((index + 1) * width), 0) for index in range(bin_count)]
    counts = [0 for _ in bins]
    for value in values:
        if value == values[-1]:
            counts[-1] += 1
            continue
        position = min(bin_count - 1, int((value - values[0]) / width))
        counts[position] += 1
    return [(start, end, counts[index]) for index, (start, end, _) in enumerate(bins)]


def _histogram_shape(values: Sequence[float]) -> str:
    mean_value = statistics.fmean(values)
    median_value = statistics.median(values)
    delta = mean_value - median_value
    if abs(delta) < max(1e-9, abs(mean_value) * 0.05):
        return "roughly symmetric"
    return "right skewed" if delta > 0 else "left skewed"


def _quartiles(values: Sequence[float]) -> tuple[float, float, float]:
    median_value = statistics.median(values)
    midpoint = len(values) // 2
    if len(values) % 2 == 0:
        lower = values[:midpoint]
        upper = values[midpoint:]
    else:
        lower = values[:midpoint]
        upper = values[midpoint + 1 :]
    q1 = statistics.median(lower) if lower else values[0]
    q3 = statistics.median(upper) if upper else values[-1]
    return (q1, median_value, q3)


def _pearson_correlation(x_values: Sequence[float], y_values: Sequence[float]) -> float | None:
    if len(x_values) < 2 or len(y_values) < 2:
        return None
    mean_x = statistics.fmean(x_values)
    mean_y = statistics.fmean(y_values)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values, strict=False))
    variance_x = sum((x - mean_x) ** 2 for x in x_values)
    variance_y = sum((y - mean_y) ** 2 for y in y_values)
    if variance_x == 0 or variance_y == 0:
        return None
    return covariance / math.sqrt(variance_x * variance_y)


def _relationship_label(correlation: float | None) -> str:
    if correlation is None:
        return "undetermined"
    if correlation >= 0.35:
        return "positive"
    if correlation <= -0.35:
        return "negative"
    return "weak"


def _scatter_outlier_count(*, x_values: Sequence[float], y_values: Sequence[float]) -> int:
    if len(x_values) < 3 or len(y_values) < 3:
        return 0
    mean_x = statistics.fmean(x_values)
    mean_y = statistics.fmean(y_values)
    std_x = statistics.pstdev(x_values)
    std_y = statistics.pstdev(y_values)
    if std_x == 0 and std_y == 0:
        return 0
    count = 0
    for x_value, y_value in zip(x_values, y_values, strict=False):
        x_outlier = std_x > 0 and abs(x_value - mean_x) > (1.5 * std_x)
        y_outlier = std_y > 0 and abs(y_value - mean_y) > (1.5 * std_y)
        if x_outlier or y_outlier:
            count += 1
    return count


def _point_extreme(*, normalized: NormalizedChartData, field_name: str) -> dict[str, Any]:
    row = max(normalized.rows, key=lambda current: float(current.get(field_name) or 0))
    return {
        "field": field_name,
        "value": _round_number(float(row.get(field_name) or 0)),
    }


def _direction(delta: float) -> str:
    if delta > 0:
        return "upward"
    if delta < 0:
        return "downward"
    return "flat"


def _round_number(value: float | int | None) -> int | float | None:
    if value is None:
        return None
    number = float(value)
    if number.is_integer():
        return int(number)
    return round(number, 2)


def _format_number(value: float | int) -> str:
    rounded = _round_number(value)
    if isinstance(rounded, int):
        return str(rounded)
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _format_percent(value: float) -> str:
    return f"{round(value * 100, 1):.1f}%".rstrip("0").rstrip(".") + "%"


def _format_label(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value).strip()


__all__ = ["ChartSummaryBuilder", "build_chart_context_contribution"]