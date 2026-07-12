"""Visualization validators for chart artifacts and context summaries."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from typing import Any

from app.visualization.chart_registry import ChartTypeRegistry
from app.visualization.errors import (
    ChartArtifactNotFoundError,
    ChartContextSummaryBuildError,
    ChartContextSummaryLimitExceededError,
    ChartDataMissingError,
    ChartDataValidationError,
    ChartEncodingError,
    ChartFollowupAmbiguousError,
    ChartPolicyDeniedError,
    ChartRowLimitExceededError,
    ChartSeriesLimitExceededError,
    UnsupportedChartTypeError,
    UnsupportedRendererError,
)
from app.visualization.models import ChartArtifact, ChartContextSummary
from app.visualization.renderer_capabilities import RendererCapabilityCatalog
from app.visualization.settings import VisualizationSettings

_TIME_SERIES_CHART_TYPES = frozenset({"line", "multi_line", "area"})
_PART_TO_WHOLE_CHART_TYPES = frozenset({"pie", "donut"})


def validate_chart_artifact(
    artifact: ChartArtifact,
    *,
    settings: VisualizationSettings,
    registry: ChartTypeRegistry,
    capability_catalog: RendererCapabilityCatalog,
) -> ChartArtifact:
    """Validate a frontend-facing chart artifact before it leaves the backend boundary."""

    registry.get(artifact.chart_type)
    if artifact.renderer not in settings.allowed_renderers:
        raise UnsupportedRendererError(
            renderer=artifact.renderer,
            supported_renderers=settings.allowed_renderers,
        )
    if not capability_catalog.supports(
        renderer=artifact.renderer,
        chart_type=artifact.chart_type,
        spec_version=artifact.spec_version,
        data_mode=artifact.data_mode,
    ):
        raise UnsupportedRendererError(
            renderer=artifact.renderer,
            supported_renderers=settings.allowed_renderers,
        )

    _validate_non_empty_text(artifact.title, label="chart title", error_cls=ChartDataValidationError)
    _validate_artifact_metadata(artifact.metadata, settings=settings)
    _ensure_json_serializable(
        artifact.model_dump(mode="json"),
        label="chart artifact",
        error_cls=ChartEncodingError,
    )

    if artifact.data is None:
        if artifact.data_ref is None:
            raise ChartDataMissingError(
                "I can generate that chart, but I need the chart data first."
            )
        _validate_artifact_size(artifact, settings=settings)
        return artifact

    rows = _validate_rows(artifact.data)
    if not rows:
        raise ChartDataMissingError(
            "I can generate that chart, but I need chart data rows first."
        )

    if artifact.data_mode == "inline" and len(rows) > settings.limits.max_rows_inline:
        raise ChartRowLimitExceededError(
            "The dataset is too large to return inline. Please filter or summarize it first."
        )
    if len(rows) > settings.limits.max_rows_artifact_store:
        raise ChartRowLimitExceededError(
            "The dataset exceeds the configured visualization row limit."
        )

    _validate_encoding_fields_exist(artifact.encoding, rows)
    _validate_series_limit(artifact, rows, settings=settings)
    _validate_category_limit(artifact, rows, settings=settings)
    _validate_chart_specific_rules(artifact, rows, settings=settings)
    _validate_artifact_size(artifact, settings=settings)

    return artifact


def validate_chart_context_summary(
    summary: ChartContextSummary,
    *,
    settings: VisualizationSettings,
) -> ChartContextSummary:
    """Validate that a chart summary remains prompt-safe and retrievable."""

    _validate_non_empty_text(
        summary.artifact_id,
        label="summary artifact_id",
        error_cls=ChartContextSummaryBuildError,
    )
    _validate_non_empty_text(
        summary.title,
        label="summary title",
        error_cls=ChartContextSummaryBuildError,
    )
    _validate_non_empty_text(
        summary.summary_text,
        label="summary_text",
        error_cls=ChartContextSummaryBuildError,
    )
    if not any((summary.x_field, summary.y_fields, summary.series_field)):
        raise ChartContextSummaryBuildError(
            "Chart summaries must include axis or series identity fields for follow-up questions."
        )
    if settings.artifact_store.exact_followup_retrieval_enabled and not summary.data_ref:
        raise ChartContextSummaryBuildError(
            "Exact follow-up retrieval requires a data_ref in the chart summary."
        )

    _validate_summary_metadata(summary=summary, settings=settings)
    _ensure_json_serializable(
        summary.model_dump(mode="json"),
        label="chart context summary",
        error_cls=ChartContextSummaryBuildError,
    )

    estimated_tokens = summary.token_estimate or estimate_chart_summary_tokens(summary)
    token_limit = min(
        settings.context_summary.max_tokens_per_chart_summary,
        settings.context_summary.max_total_visualization_context_tokens,
    )
    if estimated_tokens > token_limit:
        raise ChartContextSummaryLimitExceededError(
            "The chart summary exceeds the configured context budget."
        )

    return summary


def estimate_chart_summary_tokens(summary: ChartContextSummary) -> int:
    """Estimate prompt cost from semantic summary content rather than raw JSON keys."""

    payload = summary.model_dump(mode="json")
    fragments = list(_summary_token_fragments(payload))
    if not fragments:
        return 1
    character_count = sum(len(fragment) for fragment in fragments)
    structural_overhead = len(fragments) * 2
    return max(1, math.ceil((character_count + structural_overhead) / 5))


def _summary_token_fragments(value: Any) -> Sequence[str]:
    fragments: list[str] = []
    _collect_summary_token_fragments(value, fragments)
    return fragments


def _collect_summary_token_fragments(value: Any, fragments: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _collect_summary_token_fragments(item, fragments)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _collect_summary_token_fragments(item, fragments)
        return
    fragments.append(str(value))


def build_visualization_error_message(
    error: Exception,
    *,
    registry: ChartTypeRegistry | None = None,
) -> str:
    """Map visualization errors to deterministic user-facing messages."""

    if isinstance(error, UnsupportedChartTypeError):
        supported_types = (
            registry.supported_labels() if registry is not None else _humanize_chart_types(error.supported_types)
        )
        return (
            "I can't produce that graph type with the current chart renderer. "
            f"Supported graph types are {_format_human_list(supported_types)}."
        )
    if isinstance(error, UnsupportedRendererError):
        return "I can't produce that graph type with the current chart renderer."
    if isinstance(error, ChartRowLimitExceededError):
        return "The dataset is too large to return inline. Please filter or summarize it first."
    if isinstance(error, ChartDataMissingError):
        return _message_or_default(
            error,
            "I can generate that chart, but I need the chart data first.",
        )
    if isinstance(error, (ChartDataValidationError, ChartEncodingError)):
        return _message_or_default(
            error,
            "The data does not match the requested chart.",
        )
    if isinstance(error, ChartPolicyDeniedError):
        return "This chart cannot be generated because it is not allowed for this use case."
    if isinstance(error, ChartContextSummaryBuildError):
        return _message_or_default(
            error,
            "The chart was generated, but I could not create a follow-up summary for it.",
        )
    if isinstance(error, ChartArtifactNotFoundError):
        return _message_or_default(
            error,
            "I no longer have access to the chart data for that graph. Please regenerate it or provide the data again.",
        )
    if isinstance(error, ChartFollowupAmbiguousError):
        return _message_or_default(
            error,
            "Which chart should I use: the income chart or the expense trend chart?",
        )
    return _message_or_default(error, "I couldn't generate that chart safely.")


def _validate_rows(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, raw_row in enumerate(data):
        if not isinstance(raw_row, Mapping):
            raise ChartDataValidationError(
                f"The data does not match the requested chart. Row {index + 1} must be an object."
            )
        row = dict(raw_row)
        if not row:
            raise ChartDataValidationError(
                f"The data does not match the requested chart. Row {index + 1} must not be empty."
            )
        for field_name in row:
            _validate_field_name(field_name)
        rows.append(row)
    return rows


def _validate_encoding_fields_exist(
    encoding: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> None:
    referenced_fields: set[str] = set()
    for key in ("x", "category", "series", "value", "size", "task", "start", "end", "time", "dimension"):
        field_name = _read_optional_field_name(encoding, key)
        if field_name is not None:
            referenced_fields.add(field_name)
    referenced_fields.update(_read_field_names(encoding, "y"))

    for field_name in referenced_fields:
        if any(field_name not in row for row in rows):
            raise ChartEncodingError(
                f"The data does not match the requested chart. The field '{field_name}' is missing from at least one row."
            )


def _validate_series_limit(
    artifact: ChartArtifact,
    rows: Sequence[Mapping[str, Any]],
    *,
    settings: VisualizationSettings,
) -> None:
    series_count = _estimate_series_count(artifact, rows)
    if series_count > settings.limits.max_series:
        raise ChartSeriesLimitExceededError(
            f"The chart exceeds the configured series limit of {settings.limits.max_series}."
        )


def _validate_category_limit(
    artifact: ChartArtifact,
    rows: Sequence[Mapping[str, Any]],
    *,
    settings: VisualizationSettings,
) -> None:
    category_fields = _category_fields_for_chart(artifact)
    for field_name in category_fields:
        category_count = _count_unique_values(rows, field_name)
        if category_count > settings.limits.max_categories:
            raise ChartDataValidationError(
                f"The chart exceeds the configured category limit of {settings.limits.max_categories}."
            )


def _validate_chart_specific_rules(
    artifact: ChartArtifact,
    rows: Sequence[Mapping[str, Any]],
    *,
    settings: VisualizationSettings,
) -> None:
    chart_type = artifact.chart_type

    if chart_type in {"bar", "horizontal_bar", "line", "area", "radar"}:
        x_field = _require_field(artifact.encoding, keys=("x", "category", "dimension"), label="x")
        y_fields = _resolve_value_fields(artifact.encoding)
        _ensure_scalar_field(rows, x_field)
        _ensure_numeric_fields(rows, y_fields)
        if chart_type in _TIME_SERIES_CHART_TYPES:
            time_field = _read_optional_field_name(artifact.encoding, "time")
            if time_field is None and _rows_look_temporal(rows, x_field):
                time_field = x_field
            if time_field is not None:
                _ensure_temporal_order(rows, time_field)
        return

    if chart_type in {"grouped_bar", "stacked_bar", "multi_line"}:
        x_field = _require_field(artifact.encoding, keys=("x", "category"), label="x")
        _ensure_scalar_field(rows, x_field)
        y_fields = _read_field_names(artifact.encoding, "y")
        series_field = _read_optional_field_name(artifact.encoding, "series")
        value_field = _read_optional_field_name(artifact.encoding, "value")
        if y_fields:
            _ensure_numeric_fields(rows, y_fields)
            if len(y_fields) < 2 and series_field is None:
                raise ChartEncodingError(
                    f"{chart_type} charts require multiple y fields or a series/value encoding pair."
                )
        elif series_field is not None and value_field is not None:
            _ensure_scalar_field(rows, series_field)
            _ensure_numeric_fields(rows, (value_field,))
        else:
            raise ChartEncodingError(
                f"{chart_type} charts require multiple y fields or a series/value encoding pair."
            )
        if chart_type == "multi_line":
            time_field = _read_optional_field_name(artifact.encoding, "time")
            if time_field is None and _rows_look_temporal(rows, x_field):
                time_field = x_field
            if time_field is not None:
                _ensure_temporal_order(rows, time_field)
        return

    if chart_type in {"pie", "donut", "treemap", "waterfall"}:
        category_field = _require_field(
            artifact.encoding,
            keys=("category", "x", "dimension"),
            label="category",
        )
        value_field = _resolve_value_fields(artifact.encoding, allow_multiple=False)[0]
        _ensure_scalar_field(rows, category_field)
        values = _ensure_numeric_fields(rows, (value_field,))[value_field]
        if chart_type in _PART_TO_WHOLE_CHART_TYPES:
            if any(value < 0 for value in values):
                raise ChartDataValidationError(
                    "The data does not match the requested chart. Pie and donut charts require non-negative values."
                )
            if all(value == 0 for value in values):
                raise ChartDataValidationError(
                    "The data does not match the requested chart. Pie and donut charts require at least one non-zero value."
                )
        if chart_type == "waterfall" and all(value == 0 for value in values):
            raise ChartDataValidationError(
                "The data does not match the requested chart. Waterfall charts require at least one non-zero contribution."
            )
        return

    if chart_type == "scatter":
        x_field = _require_field(artifact.encoding, keys=("x",), label="x")
        y_field = _resolve_y_scalar_field(artifact.encoding)
        _ensure_numeric_fields(rows, (x_field, y_field))
        return

    if chart_type == "bubble":
        x_field = _require_field(artifact.encoding, keys=("x",), label="x")
        y_field = _resolve_y_scalar_field(artifact.encoding)
        size_field = _require_field(artifact.encoding, keys=("size",), label="size")
        _ensure_numeric_fields(rows, (x_field, y_field, size_field))
        return

    if chart_type == "histogram":
        value_field = _require_field(artifact.encoding, keys=("x", "value"), label="x")
        _ensure_numeric_fields(rows, (value_field,))
        return

    if chart_type == "box_plot":
        _require_field(artifact.encoding, keys=("x", "category"), label="x")
        value_fields = _resolve_value_fields(artifact.encoding, allow_multiple=False)
        _ensure_numeric_fields(rows, value_fields)
        return

    if chart_type == "heatmap":
        x_field = _require_field(artifact.encoding, keys=("x",), label="x")
        y_field = _require_field(artifact.encoding, keys=("y",), label="y")
        value_field = _require_field(artifact.encoding, keys=("value",), label="value")
        _ensure_scalar_field(rows, x_field)
        _ensure_scalar_field(rows, y_field)
        _ensure_numeric_fields(rows, (value_field,))
        return

    if chart_type == "gantt":
        task_field = _require_field(artifact.encoding, keys=("task",), label="task")
        start_field = _require_field(artifact.encoding, keys=("start",), label="start")
        end_field = _require_field(artifact.encoding, keys=("end",), label="end")
        _ensure_scalar_field(rows, task_field)
        _ensure_temporal_bounds(rows, start_field=start_field, end_field=end_field)
        return

    if chart_type == "table":
        return

    raise UnsupportedChartTypeError(
        requested_type=chart_type,
        supported_types=(chart_type,),
    )


def _validate_artifact_metadata(
    metadata: Mapping[str, Any],
    *,
    settings: VisualizationSettings,
) -> None:
    allowlist = set(settings.safe_metadata_allowlist)
    for key, value in metadata.items():
        normalized_key = _validate_field_name(key)
        if normalized_key not in allowlist:
            raise ChartEncodingError(
                f"Chart metadata contains unsupported key '{normalized_key}'."
            )
        _ensure_json_serializable(
            value,
            label=f"chart metadata '{normalized_key}'",
            error_cls=ChartEncodingError,
        )


def _validate_summary_metadata(
    *,
    summary: ChartContextSummary,
    settings: VisualizationSettings,
) -> None:
    allowlist = set(settings.safe_metadata_allowlist)
    if settings.context_summary.include_sample_rows:
        allowlist.add("sample_rows")

    for forbidden_key in ("data", "rows"):
        if forbidden_key in summary.metadata:
            raise ChartContextSummaryBuildError(
                "Chart summaries must not include full row-level data in metadata."
            )

    for key, value in summary.metadata.items():
        normalized_key = _validate_field_name(key)
        if normalized_key == "sample_rows":
            _validate_sample_rows(summary=summary, value=value, settings=settings)
            continue
        if normalized_key not in allowlist:
            raise ChartContextSummaryBuildError(
                f"Chart summary metadata contains unsupported key '{normalized_key}'."
            )
        _ensure_json_serializable(
            value,
            label=f"chart summary metadata '{normalized_key}'",
            error_cls=ChartContextSummaryBuildError,
        )


def _validate_sample_rows(
    *,
    summary: ChartContextSummary,
    value: Any,
    settings: VisualizationSettings,
) -> None:
    if not settings.context_summary.include_sample_rows:
        raise ChartContextSummaryBuildError(
            "Chart summaries must not include sample rows when sample rows are disabled."
        )
    if not isinstance(value, list):
        raise ChartContextSummaryBuildError("Sample rows must be a list of row objects.")
    if len(value) > settings.context_summary.max_sample_rows:
        raise ChartContextSummaryBuildError(
            "Chart summaries include more sample rows than the configured limit allows."
        )
    if summary.row_count > 0 and len(value) >= summary.row_count:
        raise ChartContextSummaryBuildError(
            "Chart summaries must not include the full row-level dataset."
        )
    for row in value:
        if not isinstance(row, Mapping):
            raise ChartContextSummaryBuildError("Sample rows must contain only row objects.")
        for field_name in row:
            _validate_field_name(field_name)
        _ensure_json_serializable(
            row,
            label="chart summary sample row",
            error_cls=ChartContextSummaryBuildError,
        )


def _validate_artifact_size(
    artifact: ChartArtifact,
    *,
    settings: VisualizationSettings,
) -> None:
    encoded = json.dumps(
        artifact.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > settings.limits.max_artifact_bytes:
        raise ChartEncodingError(
            f"The chart artifact exceeds the configured size limit of {settings.limits.max_artifact_bytes} bytes."
        )


def _ensure_numeric_fields(
    rows: Sequence[Mapping[str, Any]],
    field_names: Sequence[str],
) -> dict[str, list[float]]:
    numeric_values: dict[str, list[float]] = {}
    for field_name in field_names:
        values: list[float] = []
        for row in rows:
            raw_value = row.get(field_name)
            if not _is_numeric_value(raw_value):
                raise ChartDataValidationError(
                    f"The data does not match the requested chart. The field '{field_name}' must be numeric."
                )
            values.append(float(raw_value))
        numeric_values[field_name] = values
    return numeric_values


def _ensure_scalar_field(rows: Sequence[Mapping[str, Any]], field_name: str) -> None:
    for row in rows:
        value = row.get(field_name)
        if value is None or isinstance(value, (Mapping, list, tuple, set)):
            raise ChartDataValidationError(
                f"The data does not match the requested chart. The field '{field_name}' must contain scalar values."
            )


def _ensure_temporal_order(rows: Sequence[Mapping[str, Any]], field_name: str) -> None:
    temporal_values = [_parse_temporal_value(row.get(field_name)) for row in rows]
    if any(value is None for value in temporal_values):
        raise ChartDataValidationError(
            f"The data does not match the requested chart. The field '{field_name}' must contain sortable time values."
        )

    sorted_values = sorted(_temporal_sort_key(value) for value in temporal_values if value is not None)
    existing_values = [_temporal_sort_key(value) for value in temporal_values if value is not None]
    if existing_values != sorted_values:
        raise ChartDataValidationError(
            f"The data does not match the requested chart. The field '{field_name}' must be sorted in ascending time order."
        )


def _ensure_temporal_bounds(
    rows: Sequence[Mapping[str, Any]],
    *,
    start_field: str,
    end_field: str,
) -> None:
    for row in rows:
        start_value = _parse_temporal_value(row.get(start_field))
        end_value = _parse_temporal_value(row.get(end_field))
        if start_value is None or end_value is None:
            raise ChartDataValidationError(
                "The data does not match the requested chart. Gantt charts require valid start and end date fields."
            )
        if _temporal_sort_key(start_value) > _temporal_sort_key(end_value):
            raise ChartDataValidationError(
                "The data does not match the requested chart. Gantt chart start dates must be before end dates."
            )


def _estimate_series_count(
    artifact: ChartArtifact,
    rows: Sequence[Mapping[str, Any]],
) -> int:
    y_fields = _read_field_names(artifact.encoding, "y")
    if y_fields:
        return len(y_fields)
    series_field = _read_optional_field_name(artifact.encoding, "series")
    if series_field is not None:
        return _count_unique_values(rows, series_field)
    if artifact.chart_type in {"pie", "donut", "treemap", "waterfall", "scatter", "bubble", "histogram", "box_plot", "heatmap", "gantt"}:
        return 1
    return 0


def _category_fields_for_chart(artifact: ChartArtifact) -> tuple[str, ...]:
    chart_type = artifact.chart_type
    if chart_type == "heatmap":
        return tuple(
            field_name
            for field_name in (
                _read_optional_field_name(artifact.encoding, "x"),
                _read_optional_field_name(artifact.encoding, "y"),
            )
            if field_name is not None
        )
    if chart_type == "gantt":
        task_field = _read_optional_field_name(artifact.encoding, "task")
        return () if task_field is None else (task_field,)
    category_field = _read_optional_field_name(artifact.encoding, "category")
    if category_field is not None:
        return (category_field,)
    x_field = _read_optional_field_name(artifact.encoding, "x")
    if x_field is not None and chart_type not in {"scatter", "bubble", "histogram"}:
        return (x_field,)
    dimension_field = _read_optional_field_name(artifact.encoding, "dimension")
    if dimension_field is not None:
        return (dimension_field,)
    return ()


def _count_unique_values(rows: Sequence[Mapping[str, Any]], field_name: str) -> int:
    values = {
        json.dumps(row.get(field_name), sort_keys=True, default=str)
        for row in rows
    }
    return len(values)


def _resolve_value_fields(
    encoding: Mapping[str, Any],
    *,
    allow_multiple: bool = True,
) -> tuple[str, ...]:
    y_fields = _read_field_names(encoding, "y")
    if y_fields:
        if not allow_multiple and len(y_fields) > 1:
            raise ChartEncodingError("This chart type accepts only one numeric value field.")
        return y_fields
    value_field = _read_optional_field_name(encoding, "value")
    if value_field is None:
        raise ChartEncodingError("The chart encoding must include a numeric value field.")
    return (value_field,)


def _resolve_y_scalar_field(encoding: Mapping[str, Any]) -> str:
    y_fields = _read_field_names(encoding, "y")
    if len(y_fields) != 1:
        raise ChartEncodingError("Scatter and bubble charts require exactly one y field.")
    return y_fields[0]


def _require_field(
    encoding: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
    label: str,
) -> str:
    for key in keys:
        field_name = _read_optional_field_name(encoding, key)
        if field_name is not None:
            return field_name
    raise ChartEncodingError(f"The chart encoding must include '{label}'.")


def _read_optional_field_name(encoding: Mapping[str, Any], key: str) -> str | None:
    value = encoding.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        return _validate_field_name(value)
    return None


def _read_field_names(encoding: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = encoding.get(key)
    if value is None:
        return ()
    if isinstance(value, str):
        return (_validate_field_name(value),)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_validate_field_name(item) for item in value)
    raise ChartEncodingError(f"The chart encoding field '{key}' must be a string or list of strings.")


def _validate_non_empty_text(
    value: str,
    *,
    label: str,
    error_cls: type[Exception],
) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise error_cls(f"{label} must be present.")
    return value.strip()


def _validate_field_name(value: Any) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ChartEncodingError("Encoding field names must be non-empty strings.")
    normalized = value.strip()
    if len(normalized) > 128:
        raise ChartEncodingError("Encoding field names must be 128 characters or fewer.")
    if any(ord(char) < 32 for char in normalized):
        raise ChartEncodingError("Encoding field names must not contain control characters.")
    return normalized


def _ensure_json_serializable(
    value: Any,
    *,
    label: str,
    error_cls: type[Exception],
) -> None:
    try:
        json.dumps(value, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise error_cls(f"{label} must be JSON serializable.") from exc


def _is_numeric_value(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    return False


def _rows_look_temporal(rows: Sequence[Mapping[str, Any]], field_name: str) -> bool:
    parsed_values = [_parse_temporal_value(row.get(field_name)) for row in rows]
    return bool(parsed_values) and all(value is not None for value in parsed_values)


def _parse_temporal_value(value: Any) -> date | datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None

    text = value.strip()
    if text == "":
        return None

    for parser in (datetime.fromisoformat, date.fromisoformat):
        try:
            return parser(text)
        except ValueError:
            continue

    for fmt in ("%Y-%m", "%Y/%m", "%b", "%B"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _temporal_sort_key(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.combine(value, time.min)


def _humanize_chart_types(chart_types: Sequence[str]) -> tuple[str, ...]:
    return tuple(chart_type.replace("_", " ") for chart_type in chart_types)


def _format_human_list(values: Sequence[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _message_or_default(error: Exception, default: str) -> str:
    message = str(error).strip()
    return message or default


__all__ = [
    "build_visualization_error_message",
    "estimate_chart_summary_tokens",
    "validate_chart_artifact",
    "validate_chart_context_summary",
]