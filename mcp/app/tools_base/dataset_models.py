"""Shared structured dataset models for visualization-ready MCP tools."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
import math
import re
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.security.arguments import detect_secret_like_arguments


DATASET_SCHEMA_VERSION = "1.0"
QUERY_METRIC_SERIES_REQUEST_SCHEMA_ID = (
    "https://bb2.local/mcp/visualization/query_metric_series_request_v1.schema.json"
)
STRUCTURED_DATASET_RESPONSE_SCHEMA_ID = (
    "https://bb2.local/mcp/visualization/structured_dataset_response_v1.schema.json"
)
STRUCTURED_DATASET_OUTPUT_SCHEMA = "structured_dataset_v1"
DATASET_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
DATASET_ID_SEGMENT_PATTERN = re.compile(r"[^A-Za-z0-9._:-]+")
DATASET_ROW_STRING_MAX_CHARS = 500
SAFE_METADATA_STRING_MAX_CHARS = 200
REQUEST_FILTER_STRING_MAX_CHARS = 256


MetricAggregation = Literal["sum", "avg", "min", "max", "count"]
MetricGranularity = Literal["day", "week", "month", "quarter", "year", "category"]
SortOrder = Literal["asc", "desc"]
DatasetDataType = Literal["string", "integer", "number", "boolean", "date", "datetime"]
DatasetSemanticRole = Literal[
    "dimension",
    "metric",
    "time",
    "category",
    "series",
    "identifier",
    "other",
]
ScalarValue: TypeAlias = str | int | float | bool | None
SafeScalarValue: TypeAlias = str | int | float | bool | None


class StrictDatasetModel(BaseModel):
    """Base model with strict field handling for dataset contracts."""

    model_config = ConfigDict(extra="forbid")


def normalize_text(value: str) -> str:
    """Collapse repeated whitespace and trim surrounding spaces."""

    return " ".join(value.split()).strip()


def bound_text(value: str, *, max_chars: int) -> str:
    """Normalize and truncate free-form text to a safe maximum length."""

    normalized = normalize_text(value)
    if len(normalized) <= max_chars:
        return normalized
    if max_chars <= 3:
        return normalized[:max_chars]
    return normalized[: max_chars - 3].rstrip() + "..."


def generate_dataset_id(*parts: str, version_tag: str = "v1") -> str:
    """Build a deterministic, transport-safe dataset identifier."""

    segments: list[str] = []
    for part in (*parts, version_tag):
        normalized = DATASET_ID_SEGMENT_PATTERN.sub("_", normalize_text(part)).strip("._:-_")
        if normalized:
            segments.append(normalized.lower())
    if not segments:
        raise ValueError("dataset_id must include at least one non-empty segment.")
    dataset_id = ".".join(segments)
    if len(dataset_id) > 128:
        raise ValueError("dataset_id must be at most 128 characters long.")
    if DATASET_ID_PATTERN.fullmatch(dataset_id) is None:
        raise ValueError("dataset_id contains unsupported characters.")
    return dataset_id


def build_metric_series_query_summary(
    query: MetricSeriesQuery | dict[str, Any],
    *,
    row_count: int | None = None,
    truncated: bool = False,
) -> str:
    """Generate a bounded, provider-neutral dataset query summary."""

    resolved_query = (
        query
        if isinstance(query, MetricSeriesQuery)
        else MetricSeriesQuery.model_validate(query)
    )
    metric_text = ", ".join(resolved_query.metric_names)
    parts = [
        f"{resolved_query.aggregation} aggregation for metrics {metric_text}",
        f"by {resolved_query.dimension}",
        f"at {resolved_query.granularity} granularity",
    ]
    if resolved_query.start_date and resolved_query.end_date:
        parts.append(
            f"from {resolved_query.start_date.isoformat()} to {resolved_query.end_date.isoformat()}"
        )
    elif resolved_query.start_date:
        parts.append(f"starting {resolved_query.start_date.isoformat()}")
    elif resolved_query.end_date:
        parts.append(f"through {resolved_query.end_date.isoformat()}")

    if resolved_query.filters:
        parts.append(f"with {len(resolved_query.filters)} filter(s)")
    if row_count is not None:
        label = "row" if row_count == 1 else "rows"
        parts.append(f"returning {row_count} {label}")
    if truncated:
        parts.append("truncated for transport")
    return bound_text(" ".join(parts) + ".", max_chars=500)


def export_metric_series_query_json_schema() -> dict[str, Any]:
    """Return the frozen JSON schema for metric-series queries."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": QUERY_METRIC_SERIES_REQUEST_SCHEMA_ID,
        "title": "QueryMetricSeriesRequestV1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "metric_names",
            "dimension",
            "aggregation",
            "granularity",
            "sort",
            "limit",
        ],
        "properties": {
            "metric_names": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 64,
                },
            },
            "dimension": {
                "type": "string",
                "minLength": 1,
                "maxLength": 64,
            },
            "start_date": {
                "type": ["string", "null"],
                "format": "date",
            },
            "end_date": {
                "type": ["string", "null"],
                "format": "date",
            },
            "filters": {
                "type": "object",
                "default": {},
                "maxProperties": 10,
                "additionalProperties": {"$ref": "#/$defs/scalarValue"},
            },
            "aggregation": {"enum": ["sum", "avg", "min", "max", "count"]},
            "granularity": {
                "enum": ["day", "week", "month", "quarter", "year", "category"]
            },
            "sort": {"enum": ["asc", "desc"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        "$defs": {
            "scalarValue": {
                "oneOf": [
                    {"type": "string", "maxLength": 256},
                    {"type": "number"},
                    {"type": "boolean"},
                    {"type": "null"},
                ]
            }
        },
    }


def export_structured_dataset_response_json_schema() -> dict[str, Any]:
    """Return the frozen JSON schema for structured dataset responses."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": STRUCTURED_DATASET_RESPONSE_SCHEMA_ID,
        "title": "StructuredDatasetResponseV1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "dataset_id",
            "columns",
            "rows",
            "row_count",
            "truncated",
            "source",
            "query_summary",
            "warnings",
            "provenance",
        ],
        "properties": {
            "schema_version": {"const": DATASET_SCHEMA_VERSION},
            "dataset_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "pattern": DATASET_ID_PATTERN.pattern,
            },
            "columns": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": {"$ref": "#/$defs/datasetColumn"},
            },
            "rows": {
                "type": "array",
                "minItems": 0,
                "maxItems": 100,
                "items": {"$ref": "#/$defs/datasetRow"},
            },
            "row_count": {"type": "integer", "minimum": 0, "maximum": 100},
            "total_row_count": {
                "type": ["integer", "null"],
                "minimum": 0,
                "maximum": 1000,
            },
            "truncated": {"type": "boolean"},
            "source": {"type": "string", "minLength": 1, "maxLength": 100},
            "query_summary": {"type": "string", "minLength": 1, "maxLength": 500},
            "time_range": {
                "oneOf": [
                    {"type": "null"},
                    {"$ref": "#/$defs/timeRange"},
                ]
            },
            "warnings": {
                "type": "array",
                "maxItems": 10,
                "items": {"type": "string", "minLength": 1, "maxLength": 200},
            },
            "provenance": {
                "type": "object",
                "maxProperties": 12,
                "additionalProperties": {"$ref": "#/$defs/safeScalar"},
            },
        },
        "$defs": {
            "datasetColumn": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "data_type", "nullable", "semantic_role"],
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 64},
                    "data_type": {
                        "enum": [
                            "string",
                            "integer",
                            "number",
                            "boolean",
                            "date",
                            "datetime",
                        ]
                    },
                    "nullable": {"type": "boolean"},
                    "semantic_role": {
                        "enum": [
                            "dimension",
                            "metric",
                            "time",
                            "category",
                            "series",
                            "identifier",
                            "other",
                        ]
                    },
                    "unit": {
                        "type": ["string", "null"],
                        "minLength": 1,
                        "maxLength": 32,
                    },
                },
            },
            "datasetRow": {
                "type": "object",
                "maxProperties": 20,
                "additionalProperties": {"$ref": "#/$defs/scalarValue"},
            },
            "timeRange": {
                "type": "object",
                "additionalProperties": False,
                "required": ["start", "end"],
                "properties": {
                    "start": {"type": "string", "format": "date"},
                    "end": {"type": "string", "format": "date"},
                },
            },
            "scalarValue": {
                "oneOf": [
                    {"type": "string", "maxLength": DATASET_ROW_STRING_MAX_CHARS},
                    {"type": "number"},
                    {"type": "boolean"},
                    {"type": "null"},
                ]
            },
            "safeScalar": {
                "oneOf": [
                    {"type": "string", "maxLength": SAFE_METADATA_STRING_MAX_CHARS},
                    {"type": "number"},
                    {"type": "boolean"},
                    {"type": "null"},
                ]
            },
        },
    }


class MetricSeriesQuery(StrictDatasetModel):
    """Validated request model for the reporting metric-series tool."""

    metric_names: list[str] = Field(min_length=1, max_length=5)
    dimension: str = Field(min_length=1, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    filters: dict[str, ScalarValue] = Field(default_factory=dict, max_length=10)
    aggregation: MetricAggregation = "sum"
    granularity: MetricGranularity = "month"
    sort: SortOrder = "asc"
    limit: int = Field(default=100, ge=1, le=100)

    @field_validator("metric_names", mode="before")
    @classmethod
    def normalize_metric_names(cls, value: Any) -> Any:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            return value
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                normalized.append(item)
                continue
            cleaned = item.strip()
            if not cleaned:
                raise ValueError("metric_names must not contain blank values.")
            normalized.append(cleaned)
        return normalized

    @field_validator("dimension", mode="before")
    @classmethod
    def normalize_dimension(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("dimension must not be blank.")
        return cleaned

    @field_validator("filters", mode="before")
    @classmethod
    def normalize_filters(cls, value: Any) -> Any:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            return value
        normalized: dict[str, ScalarValue] = {}
        for key, item in value.items():
            key_text = str(key).strip()
            if not key_text:
                raise ValueError("filters must not contain blank keys.")
            normalized[key_text] = _normalize_scalar_value(item)
        return normalized

    @model_validator(mode="after")
    def validate_request(self) -> MetricSeriesQuery:
        for key, value in self.filters.items():
            _validate_scalar_value(
                value,
                path=f"filters.{key}",
                max_string_chars=REQUEST_FILTER_STRING_MAX_CHARS,
            )
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be less than or equal to end_date.")
        return self


class DatasetColumn(StrictDatasetModel):
    """Typed metadata for one structured dataset column."""

    name: str = Field(min_length=1, max_length=64)
    data_type: DatasetDataType
    nullable: bool = True
    semantic_role: DatasetSemanticRole = "other"
    unit: str | None = Field(default=None, min_length=1, max_length=32)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("column names must not be blank.")
        return cleaned

    @field_validator("unit", mode="before")
    @classmethod
    def normalize_unit(cls, value: Any) -> Any:
        if value is None or not isinstance(value, str):
            return value
        cleaned = normalize_text(value)
        return cleaned or None


class DatasetTimeRange(StrictDatasetModel):
    """Explicit time bounds for structured dataset results."""

    start: date
    end: date

    @model_validator(mode="after")
    def validate_range(self) -> DatasetTimeRange:
        if self.start > self.end:
            raise ValueError("time_range.start must be less than or equal to time_range.end.")
        return self


class StructuredDatasetResponse(StrictDatasetModel):
    """Validated, bounded dataset payload returned by visualization-ready tools."""

    schema_version: Literal[DATASET_SCHEMA_VERSION] = DATASET_SCHEMA_VERSION
    dataset_id: str = Field(min_length=1, max_length=128, pattern=DATASET_ID_PATTERN.pattern)
    columns: list[DatasetColumn] = Field(min_length=1, max_length=20)
    rows: list[dict[str, ScalarValue]] = Field(default_factory=list, max_length=100)
    row_count: int = Field(ge=0, le=100)
    total_row_count: int | None = Field(default=None, ge=0, le=1000)
    truncated: bool = False
    source: str = Field(min_length=1, max_length=100)
    query_summary: str = Field(min_length=1, max_length=500)
    time_range: DatasetTimeRange | None = None
    warnings: list[str] = Field(default_factory=list, max_length=10)
    provenance: dict[str, SafeScalarValue] = Field(default_factory=dict, max_length=12)

    @field_validator("dataset_id", mode="before")
    @classmethod
    def normalize_dataset_id(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("dataset_id must not be blank.")
        return cleaned

    @field_validator("source", "query_summary", mode="before")
    @classmethod
    def normalize_bounded_text(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        cleaned = normalize_text(value)
        if not cleaned:
            raise ValueError("dataset text fields must not be blank.")
        return cleaned

    @field_validator("warnings", mode="before")
    @classmethod
    def normalize_warnings(cls, value: Any) -> Any:
        if value is None:
            return []
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            return value
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                normalized.append(item)
                continue
            cleaned = normalize_text(item)
            if not cleaned:
                raise ValueError("warnings must not contain blank values.")
            normalized.append(cleaned)
        return normalized

    @field_validator("rows", mode="before")
    @classmethod
    def normalize_rows(cls, value: Any) -> Any:
        if value is None:
            return []
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            return value
        normalized_rows: list[dict[str, ScalarValue]] = []
        for row in value:
            if not isinstance(row, Mapping):
                normalized_rows.append(row)
                continue
            normalized_row: dict[str, ScalarValue] = {}
            for key, item in row.items():
                key_text = str(key).strip()
                if not key_text:
                    raise ValueError("rows must not contain blank field names.")
                normalized_row[key_text] = _normalize_scalar_value(item)
            normalized_rows.append(normalized_row)
        return normalized_rows

    @field_validator("provenance", mode="before")
    @classmethod
    def normalize_provenance(cls, value: Any) -> Any:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            return value
        normalized: dict[str, SafeScalarValue] = {}
        for key, item in value.items():
            key_text = str(key).strip()
            if not key_text:
                raise ValueError("provenance keys must not be blank.")
            normalized[key_text] = _normalize_scalar_value(item)
        return normalized

    @model_validator(mode="after")
    def validate_dataset(self) -> StructuredDatasetResponse:
        column_names = [column.name for column in self.columns]
        duplicate_columns = sorted({name for name in column_names if column_names.count(name) > 1})
        if duplicate_columns:
            raise ValueError(
                "columns must not contain duplicate names: " + ", ".join(duplicate_columns)
            )

        if self.row_count != len(self.rows):
            raise ValueError("row_count must match the number of rows.")
        if self.total_row_count is not None and self.total_row_count < self.row_count:
            raise ValueError("total_row_count must be greater than or equal to row_count.")
        if self.truncated:
            if self.total_row_count is not None and self.total_row_count <= self.row_count:
                raise ValueError(
                    "truncated datasets must declare total_row_count greater than row_count."
                )
        elif self.total_row_count is not None and self.total_row_count != self.row_count:
            raise ValueError(
                "non-truncated datasets must declare total_row_count equal to row_count."
            )

        columns_by_name = {column.name: column for column in self.columns}
        for column in self.columns:
            if column.semantic_role == "metric" and column.data_type not in {"integer", "number"}:
                raise ValueError(
                    f"metric column {column.name!r} must use integer or number data_type."
                )

        for row_index, row in enumerate(self.rows):
            if len(row) > 20:
                raise ValueError("rows must not contain more than 20 fields.")
            unknown_fields = sorted(set(row) - set(columns_by_name))
            if unknown_fields:
                raise ValueError(
                    "rows must not contain unknown fields: " + ", ".join(unknown_fields)
                )
            for column_name, column in columns_by_name.items():
                if column_name not in row:
                    if not column.nullable:
                        raise ValueError(
                            f"rows[{row_index}] is missing required field {column_name!r}."
                        )
                    continue
                _validate_row_value(
                    row[column_name],
                    column=column,
                    path=f"rows[{row_index}].{column_name}",
                )

        for key, value in self.provenance.items():
            _validate_scalar_value(
                value,
                path=f"provenance.{key}",
                max_string_chars=SAFE_METADATA_STRING_MAX_CHARS,
            )

        findings = detect_secret_like_arguments(
            {
                "source": self.source,
                "query_summary": self.query_summary,
                "warnings": self.warnings,
                "provenance": self.provenance,
            },
            path="dataset",
        )
        if findings:
            raise ValueError("dataset metadata must not contain secret-like keys or values.")
        return self


def _normalize_scalar_value(value: Any) -> ScalarValue:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _validate_scalar_value(value: ScalarValue, *, path: str, max_string_chars: int) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        return
    if isinstance(value, str):
        if len(value) > max_string_chars:
            raise ValueError(f"{path} must be at most {max_string_chars} characters long.")
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must not contain non-finite numeric values.")
        return
    raise ValueError(f"{path} must contain only scalar JSON-compatible values.")


def _validate_row_value(value: ScalarValue, *, column: DatasetColumn, path: str) -> None:
    if value is None:
        if not column.nullable:
            raise ValueError(f"{path} must not be null.")
        return

    if column.data_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string.")
        if len(value) > DATASET_ROW_STRING_MAX_CHARS:
            raise ValueError(
                f"{path} must be at most {DATASET_ROW_STRING_MAX_CHARS} characters long."
            )
        return

    if column.data_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{path} must be an integer.")
        return

    if column.data_type == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{path} must be numeric.")
        if not math.isfinite(float(value)):
            raise ValueError(f"{path} must not contain non-finite numeric values.")
        return

    if column.data_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{path} must be a boolean.")
        return

    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string.")
    if len(value) > DATASET_ROW_STRING_MAX_CHARS:
        raise ValueError(
            f"{path} must be at most {DATASET_ROW_STRING_MAX_CHARS} characters long."
        )
    if column.data_type == "date":
        _parse_iso_date(value, path=path)
        return
    _parse_iso_datetime(value, path=path)


def _parse_iso_date(value: str, *, path: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{path} must be a valid ISO date string.") from exc


def _parse_iso_datetime(value: str, *, path: str) -> datetime:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{path} must be a valid ISO datetime string.") from exc