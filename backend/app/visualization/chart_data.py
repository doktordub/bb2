"""Normalization helpers for deterministic visualization artifact building."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from app.visualization.errors import ChartDataMissingError, ChartDataValidationError, ChartEncodingError

FieldKind = Literal["numeric", "temporal", "boolean", "text", "empty"]

_MONTH_NAME_PATTERN = re.compile(r"^[A-Za-z]{3,9}$")
_MONTH_GRANULARITY_PATTERN = re.compile(r"^\d{4}[-/]\d{2}$")


@dataclass(frozen=True, slots=True)
class ChartFieldProfile:
    """Normalized field profile inferred from row data."""

    name: str
    kind: FieldKind
    nullable: bool
    distinct_count: int


@dataclass(frozen=True, slots=True)
class NormalizedChartData:
    """Stable, JSON-safe row model consumed by visualization builders."""

    rows: tuple[dict[str, Any], ...]
    fields: tuple[str, ...]
    field_profiles: dict[str, ChartFieldProfile]
    warnings: tuple[str, ...] = ()

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def profile_for(self, field_name: str) -> ChartFieldProfile:
        try:
            return self.field_profiles[field_name]
        except KeyError as exc:
            raise ChartEncodingError(f"Unknown chart field '{field_name}'.") from exc

    def rows_as_list(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.rows]


def normalize_chart_data(records: Sequence[Mapping[str, Any]]) -> NormalizedChartData:
    """Normalize raw chart records into a stable row model."""

    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise ChartDataValidationError("Chart data must be a sequence of row objects.")
    if not records:
        raise ChartDataMissingError("I can generate that chart, but I need chart data rows first.")

    field_order: list[str] = []
    seen_fields: set[str] = set()
    raw_rows: list[dict[str, Any]] = []

    for index, raw_record in enumerate(records):
        if not isinstance(raw_record, Mapping):
            raise ChartDataValidationError(
                f"The data does not match the requested chart. Row {index + 1} must be an object."
            )
        if not raw_record:
            raise ChartDataValidationError(
                f"The data does not match the requested chart. Row {index + 1} must not be empty."
            )

        row: dict[str, Any] = {}
        for raw_field_name, raw_value in raw_record.items():
            field_name = validate_chart_field_name(raw_field_name)
            row[field_name] = raw_value
            if field_name not in seen_fields:
                field_order.append(field_name)
                seen_fields.add(field_name)
        raw_rows.append(row)

    field_profiles = {
        field_name: _infer_field_profile(field_name, [row.get(field_name) for row in raw_rows])
        for field_name in field_order
    }

    warnings: list[str] = []
    normalized_rows: list[dict[str, Any]] = []
    sparse_field_detected = False
    for raw_row in raw_rows:
        normalized_row: dict[str, Any] = {}
        for field_name in field_order:
            if field_name not in raw_row:
                sparse_field_detected = True
            normalized_row[field_name] = _normalize_value(raw_row.get(field_name), field_profiles[field_name])
        normalized_rows.append(normalized_row)

    if sparse_field_detected:
        warnings.append("Some chart rows were normalized with missing optional fields set to null.")

    return NormalizedChartData(
        rows=tuple(normalized_rows),
        fields=tuple(field_order),
        field_profiles=field_profiles,
        warnings=tuple(warnings),
    )


def validate_chart_field_name(value: Any) -> str:
    """Validate a visualization field name using the phase-2 encoding rules."""

    if not isinstance(value, str) or value.strip() == "":
        raise ChartEncodingError("Encoding field names must be non-empty strings.")
    normalized = value.strip()
    if len(normalized) > 128:
        raise ChartEncodingError("Encoding field names must be 128 characters or fewer.")
    if any(ord(char) < 32 for char in normalized):
        raise ChartEncodingError("Encoding field names must not contain control characters.")
    return normalized


def count_unique_values(rows: Sequence[Mapping[str, Any]], field_name: str) -> int:
    """Count distinct values deterministically for one field."""

    return len(
        {
            json.dumps(row.get(field_name), sort_keys=True, separators=(",", ":"), default=str)
            for row in rows
        }
    )


def parse_temporal_value(value: Any) -> date | datetime | time | None:
    """Parse one scalar as a temporal value without changing string semantics."""

    if isinstance(value, datetime):
        return value
    if isinstance(value, time):
        return value
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None

    text = value.strip()
    if text == "":
        return None

    for parser in (datetime.fromisoformat, date.fromisoformat, time.fromisoformat):
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


def temporal_sort_key(value: date | datetime | time) -> datetime:
    """Build a sortable datetime key for dates, datetimes, and times."""

    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    return datetime.combine(date.min, value)


def infer_time_range(
    rows: Sequence[Mapping[str, Any]],
    *,
    field_name: str | None = None,
    start_field: str | None = None,
    end_field: str | None = None,
) -> dict[str, Any] | None:
    """Infer a bounded time range from one temporal field or start/end bounds."""

    if field_name is not None:
        values: list[tuple[date | datetime | time, Any]] = []
        for row in rows:
            raw_value = row.get(field_name)
            parsed = parse_temporal_value(raw_value)
            if parsed is None:
                return None
            values.append((parsed, raw_value))
        if not values:
            return None
        start_value = min(values, key=lambda item: temporal_sort_key(item[0]))[1]
        end_value = max(values, key=lambda item: temporal_sort_key(item[0]))[1]
        return {
            "start": _display_temporal_value(start_value),
            "end": _display_temporal_value(end_value),
            "granularity": _infer_granularity([value for _, value in values]),
        }

    if start_field is None or end_field is None:
        return None

    starts: list[tuple[date | datetime | time, Any]] = []
    ends: list[tuple[date | datetime | time, Any]] = []
    for row in rows:
        raw_start = row.get(start_field)
        raw_end = row.get(end_field)
        parsed_start = parse_temporal_value(raw_start)
        parsed_end = parse_temporal_value(raw_end)
        if parsed_start is None or parsed_end is None:
            return None
        starts.append((parsed_start, raw_start))
        ends.append((parsed_end, raw_end))

    if not starts or not ends:
        return None

    start_value = min(starts, key=lambda item: temporal_sort_key(item[0]))[1]
    end_value = max(ends, key=lambda item: temporal_sort_key(item[0]))[1]
    return {
        "start": _display_temporal_value(start_value),
        "end": _display_temporal_value(end_value),
        "granularity": _infer_granularity([value for _, value in starts + ends]),
    }


def _infer_field_profile(field_name: str, values: Sequence[Any]) -> ChartFieldProfile:
    non_null_values = [value for value in values if value is not None]
    if not non_null_values:
        return ChartFieldProfile(
            name=field_name,
            kind="empty",
            nullable=True,
            distinct_count=0,
        )

    if any(_is_non_scalar(value) for value in non_null_values):
        raise ChartDataValidationError(
            f"The data does not match the requested chart. The field '{field_name}' must contain scalar values."
        )

    numeric_values = [_coerce_numeric_value(value) for value in non_null_values]
    if all(value is not None for value in numeric_values):
        return ChartFieldProfile(
            name=field_name,
            kind="numeric",
            nullable=len(non_null_values) != len(values),
            distinct_count=len({_stable_identity(value) for value in numeric_values}),
        )
    if any(value is not None for value in numeric_values):
        raise ChartDataValidationError(
            f"The data does not match the requested chart. The field '{field_name}' mixes numeric and non-numeric values."
        )

    temporal_values = [parse_temporal_value(value) for value in non_null_values]
    if all(value is not None for value in temporal_values):
        return ChartFieldProfile(
            name=field_name,
            kind="temporal",
            nullable=len(non_null_values) != len(values),
            distinct_count=len({_stable_identity(value) for value in non_null_values}),
        )
    if any(value is not None for value in temporal_values) or any(
        isinstance(value, (date, datetime, time)) for value in non_null_values
    ):
        raise ChartDataValidationError(
            f"The data does not match the requested chart. The field '{field_name}' mixes temporal and non-temporal values."
        )

    if all(isinstance(value, bool) for value in non_null_values):
        return ChartFieldProfile(
            name=field_name,
            kind="boolean",
            nullable=len(non_null_values) != len(values),
            distinct_count=len({_stable_identity(value) for value in non_null_values}),
        )
    if any(isinstance(value, bool) for value in non_null_values):
        raise ChartDataValidationError(
            f"The data does not match the requested chart. The field '{field_name}' mixes boolean and non-boolean values."
        )

    return ChartFieldProfile(
        name=field_name,
        kind="text",
        nullable=len(non_null_values) != len(values),
        distinct_count=len({_stable_identity(str(value).strip()) for value in non_null_values}),
    )


def _normalize_value(value: Any, profile: ChartFieldProfile) -> Any:
    if value is None:
        return None

    if profile.kind == "numeric":
        coerced = _coerce_numeric_value(value)
        if coerced is None:
            raise ChartDataValidationError(
                f"The data does not match the requested chart. The field '{profile.name}' must be numeric."
            )
        return coerced

    if profile.kind == "temporal":
        if isinstance(value, (datetime, date, time)):
            return value.isoformat()
        return str(value).strip()

    if profile.kind == "boolean":
        if not isinstance(value, bool):
            raise ChartDataValidationError(
                f"The data does not match the requested chart. The field '{profile.name}' must be boolean."
            )
        return value

    if profile.kind == "text":
        return str(value).strip()

    return value


def _coerce_numeric_value(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return int(value) if value.is_integer() else value
    if not isinstance(value, str):
        return None

    text = value.strip()
    if text == "":
        return None

    try:
        decimal_value = Decimal(text)
    except InvalidOperation:
        return None

    if not decimal_value.is_finite():
        return None

    if decimal_value == decimal_value.to_integral_value():
        return int(decimal_value)
    return float(decimal_value)


def _display_temporal_value(value: Any) -> str:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value).strip()


def _infer_granularity(values: Sequence[Any]) -> str:
    normalized_values = [str(value).strip() for value in values if str(value).strip() != ""]
    if not normalized_values:
        return "unknown"
    if any("T" in value or ":" in value for value in normalized_values):
        return "datetime"
    if all(_MONTH_GRANULARITY_PATTERN.fullmatch(value) for value in normalized_values):
        return "month"
    if all(_MONTH_NAME_PATTERN.fullmatch(value) for value in normalized_values):
        return "month"
    if all(len(value) == 10 and value[4] == "-" and value[7] == "-" for value in normalized_values):
        return "day"
    return "time"


def _stable_identity(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _is_non_scalar(value: Any) -> bool:
    return isinstance(value, (Mapping, list, tuple, set))


__all__ = [
    "ChartFieldProfile",
    "NormalizedChartData",
    "count_unique_values",
    "infer_time_range",
    "normalize_chart_data",
    "parse_temporal_value",
    "temporal_sort_key",
    "validate_chart_field_name",
]