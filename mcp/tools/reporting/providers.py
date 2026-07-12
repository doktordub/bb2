"""Provider adapters and normalized tool errors for the reporting MCP plugin."""

from __future__ import annotations

import math
from pathlib import Path
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.context import ToolRuntimeContext
from app.errors import MCPToolConfigurationError, ToolInputValidationError
from app.tools_base.dataset_models import (
    DATASET_SCHEMA_VERSION,
    STRUCTURED_DATASET_OUTPUT_SCHEMA,
    DatasetColumn,
    DatasetTimeRange,
    MetricAggregation,
    MetricGranularity,
    MetricSeriesQuery,
    SafeScalarValue,
    ScalarValue,
    StructuredDatasetResponse,
    build_metric_series_query_summary,
    bound_text,
    generate_dataset_id,
)
from app.tools_base.results import ToolErrorEnvelope, ToolResultEnvelope, ToolResultSummary

from tools.reporting.models import ReportingToolConfig


TOOL_NAME = "reporting.query_metric_series"
REPORTING_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "reporting"


def _build_error_envelope(
    *,
    tool_name: str,
    code: str,
    message: str,
    retryable: bool,
    details: dict[str, SafeScalarValue],
    summary: str | None,
) -> ToolResultEnvelope:
    error_message = bound_text(message, max_chars=200)
    summary_message = bound_text(summary or error_message, max_chars=200)
    return ToolResultEnvelope(
        ok=False,
        tool_name=tool_name,
        summary=ToolResultSummary(message=summary_message, item_count=0, truncated=False),
        data={},
        errors=[
            ToolErrorEnvelope(
                code=code,
                message=error_message,
                retryable=retryable,
                details=details,
            )
        ],
        meta={
            "schema_version": DATASET_SCHEMA_VERSION,
            "output_schema": STRUCTURED_DATASET_OUTPUT_SCHEMA,
        },
    )


class ReportingValidationError(ToolInputValidationError):
    """Safe query-validation error that can be returned as a structured tool result."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        summary: str | None = None,
        retryable: bool = False,
        details: dict[str, SafeScalarValue] | None = None,
    ) -> None:
        safe_message = bound_text(message, max_chars=200)
        super().__init__(safe_message)
        self.code = code
        self.message = safe_message
        self.summary = bound_text(summary or safe_message, max_chars=200)
        self.retryable = retryable
        self.details = dict(details or {})

    def to_result_envelope(self, *, tool_name: str) -> ToolResultEnvelope:
        return _build_error_envelope(
            tool_name=tool_name,
            code=self.code,
            message=self.message,
            retryable=self.retryable,
            details=self.details,
            summary=self.summary,
        )


class ReportingProviderError(RuntimeError):
    """Safe provider/runtime error that can be returned as a structured tool result."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        summary: str | None = None,
        retryable: bool = False,
        details: dict[str, SafeScalarValue] | None = None,
    ) -> None:
        safe_message = bound_text(message, max_chars=200)
        super().__init__(safe_message)
        self.code = code
        self.message = safe_message
        self.summary = bound_text(summary or safe_message, max_chars=200)
        self.retryable = retryable
        self.details = dict(details or {})

    def to_result_envelope(self, *, tool_name: str) -> ToolResultEnvelope:
        return _build_error_envelope(
            tool_name=tool_name,
            code=self.code,
            message=self.message,
            retryable=self.retryable,
            details=self.details,
            summary=self.summary,
        )

    @classmethod
    def from_dataset_contract_error(cls, error: Exception) -> "ReportingProviderError":
        message = str(error)
        if "max_result_bytes" in message or "result exceeds" in message:
            return cls(
                "result_too_large",
                "Reporting provider returned more data than this tool is allowed to send.",
                summary="The reporting result exceeded the transport limits.",
                retryable=False,
            )

        return cls(
            "schema_mismatch",
            "Reporting provider returned data that does not match the visualization dataset contract.",
            summary="The reporting provider returned an invalid dataset shape.",
            retryable=False,
        )


class ReportingProvider(Protocol):
    """Provider contract for approved reporting data sources."""

    @property
    def trusted_scope(self) -> dict[str, ScalarValue]:
        ...

    async def query_metric_series(
        self,
        request: MetricSeriesQuery,
        *,
        trusted_scope: dict[str, ScalarValue],
    ) -> StructuredDatasetResponse:
        ...

    async def query_category_summary(
        self,
        request: Any,
        *,
        trusted_scope: dict[str, ScalarValue],
    ) -> StructuredDatasetResponse:
        ...

    def health(self, *, deep: bool = False) -> dict[str, object]:
        ...


class FixtureMetricDefinition(BaseModel):
    """Metric field mapping loaded from one approved fixture dataset."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=64)
    unit: str | None = Field(default=None, min_length=1, max_length=32)


class FixtureDatasetDefinition(BaseModel):
    """Fixture dataset metadata and raw rows used by the local provider."""

    model_config = ConfigDict(extra="forbid")

    dataset_name: str = Field(min_length=1, max_length=64)
    source: str = Field(default="reporting_fixture", min_length=1, max_length=100)
    default_granularity: MetricGranularity = "month"
    default_aggregation: MetricAggregation = "sum"
    scope: dict[str, str] = Field(default_factory=dict, min_length=1, max_length=8)
    dimensions: dict[str, str] = Field(min_length=1, max_length=8)
    metrics: dict[str, FixtureMetricDefinition] = Field(min_length=1, max_length=12)
    rows: list[dict[str, ScalarValue]] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_rows(self) -> "FixtureDatasetDefinition":
        required_fields = set(self.dimensions.values()) | {
            metric_definition.field for metric_definition in self.metrics.values()
        }
        for index, row in enumerate(self.rows):
            missing_fields = sorted(required_fields - set(row))
            if missing_fields:
                raise ValueError(
                    f"fixture row {index} is missing required fields: {', '.join(missing_fields)}"
                )

            for dimension_field in self.dimensions.values():
                raw_value = row[dimension_field]
                if not isinstance(raw_value, str):
                    raise ValueError(
                        f"fixture row {index} field {dimension_field!r} must be an ISO date string."
                    )
                try:
                    date.fromisoformat(raw_value)
                except ValueError as error:
                    raise ValueError(
                        f"fixture row {index} field {dimension_field!r} must be an ISO date string."
                    ) from error

            for metric_name, metric_definition in self.metrics.items():
                raw_value = row[metric_definition.field]
                if not isinstance(raw_value, (int, float)) or not math.isfinite(float(raw_value)):
                    raise ValueError(
                        f"fixture row {index} metric {metric_name!r} must be numeric and finite."
                    )

        return self


@dataclass(slots=True)
class FixtureReportingProvider:
    """Approved local reporting provider backed by fixture JSON data."""

    context: ToolRuntimeContext
    config: ReportingToolConfig
    fixture_path: Path | None = None
    fixture: FixtureDatasetDefinition = field(init=False, repr=False)
    _rows: tuple[dict[str, object], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.fixture = self._load_fixture()
        self._rows = tuple(self._load_rows())

    @property
    def trusted_scope(self) -> dict[str, ScalarValue]:
        return dict(self.fixture.scope)

    async def query_metric_series(
        self,
        request: MetricSeriesQuery,
        *,
        trusted_scope: dict[str, ScalarValue],
    ) -> StructuredDatasetResponse:
        provider_dimension = self.fixture.dimensions.get(request.dimension)
        if provider_dimension is None:
            raise ReportingProviderError(
                "schema_mismatch",
                f"Reporting fixture does not define dimension {request.dimension!r}.",
                summary="The reporting fixture is missing the requested dimension mapping.",
            )

        self._validate_scope(request.filters, trusted_scope)

        metric_fields: dict[str, str] = {}
        for metric_name in request.metric_names:
            metric_definition = self.fixture.metrics.get(metric_name)
            if metric_definition is None:
                raise ReportingProviderError(
                    "schema_mismatch",
                    f"Reporting fixture does not define metric {metric_name!r}.",
                    summary="The reporting fixture is missing the requested metric mapping.",
                )
            metric_fields[metric_name] = metric_definition.field

        filtered_rows = self._filter_rows(request, provider_dimension)

        columns = [
            DatasetColumn(
                name=request.dimension,
                data_type="date",
                nullable=False,
                semantic_role="time",
            )
        ]
        columns.extend(
            DatasetColumn(
                name=metric_name,
                data_type="number",
                nullable=False,
                semantic_role="metric",
                unit=self.fixture.metrics[metric_name].unit,
            )
            for metric_name in request.metric_names
        )

        rows = [
            {
                request.dimension: row[provider_dimension].isoformat(),
                **{
                    metric_name: float(row[provider_field])
                    for metric_name, provider_field in metric_fields.items()
                },
            }
            for row in filtered_rows
        ]

        query_summary = build_metric_series_query_summary(
            request,
            row_count=len(rows),
            truncated=False,
        )

        return StructuredDatasetResponse(
            dataset_id=generate_dataset_id(
                "reporting",
                "metric_series",
                self.fixture.dataset_name,
                request.dimension,
                "_".join(request.metric_names),
            ),
            columns=columns,
            rows=rows,
            row_count=len(rows),
            total_row_count=len(rows),
            truncated=False,
            source=self.fixture.source,
            query_summary=query_summary,
            time_range=self._resolve_time_range(filtered_rows, provider_dimension, request),
            warnings=[],
            provenance={
                "provider": self.config.provider,
                "tool_name": TOOL_NAME,
                "fixture_dataset": self.fixture.dataset_name,
                "aggregation": request.aggregation,
                "granularity": request.granularity,
                "metric_count": len(request.metric_names),
                "filter_count": len(request.filters),
            },
        )

    async def query_category_summary(
        self,
        request: Any,
        *,
        trusted_scope: dict[str, ScalarValue],
    ) -> StructuredDatasetResponse:
        del request, trusted_scope
        raise ReportingProviderError(
            "invalid_query",
            "Category-summary queries are not implemented for the fixture reporting provider.",
            summary="Category-summary queries are not available for this reporting provider yet.",
            retryable=False,
        )

    def health(self, *, deep: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "provider": self.config.provider,
            "provider_check": "fixture" if deep else "skipped",
        }
        if deep:
            payload["fixture_rows"] = len(self._rows)
            payload["fixture_scope_filters"] = len(self.fixture.scope)
        return payload

    def _load_fixture(self) -> FixtureDatasetDefinition:
        fixture_path = self.fixture_path or REPORTING_FIXTURE_DIR / f"{self.config.fixture_dataset}.json"
        try:
            raw_text = fixture_path.read_text(encoding="utf-8")
        except OSError as error:
            raise MCPToolConfigurationError(
                f"Unable to read reporting fixture dataset {fixture_path.name!r}: {error}"
            ) from error

        try:
            fixture = FixtureDatasetDefinition.model_validate_json(raw_text)
        except ValidationError as error:
            raise MCPToolConfigurationError(
                f"Invalid reporting fixture dataset {fixture_path.name!r}: {error}"
            ) from error

        if fixture.dataset_name != self.config.fixture_dataset:
            raise MCPToolConfigurationError(
                "Reporting fixture dataset name does not match the configured fixture_dataset."
            )
        return fixture

    def _load_rows(self) -> list[dict[str, object]]:
        normalized_rows: list[dict[str, object]] = []
        for row in self.fixture.rows:
            normalized_row: dict[str, object] = {}
            for key, value in row.items():
                if key in self.fixture.dimensions.values():
                    assert isinstance(value, str)
                    normalized_row[key] = date.fromisoformat(value)
                    continue
                normalized_row[key] = float(value) if isinstance(value, (int, float)) else value
            normalized_rows.append(normalized_row)
        return normalized_rows

    def _validate_scope(
        self,
        request_filters: dict[str, ScalarValue],
        trusted_scope: dict[str, ScalarValue],
    ) -> None:
        if set(request_filters) != set(trusted_scope):
            raise ReportingProviderError(
                "unauthorized_scope",
                "Reporting scope filters did not match the approved provider scope.",
                summary="The requested reporting scope is not authorized.",
            )

        for key, expected_value in trusted_scope.items():
            if request_filters.get(key) != expected_value:
                raise ReportingProviderError(
                    "unauthorized_scope",
                    f"Filter {key!r} does not match the approved provider scope.",
                    summary="The requested reporting scope is not authorized.",
                    details={"field": key, "value": str(request_filters.get(key))},
                )

    def _filter_rows(
        self,
        request: MetricSeriesQuery,
        provider_dimension: str,
    ) -> list[dict[str, object]]:
        filtered_rows: list[dict[str, object]] = []
        for row in self._rows:
            reporting_period = row[provider_dimension]
            assert isinstance(reporting_period, date)
            if request.start_date and reporting_period < request.start_date:
                continue
            if request.end_date and reporting_period > request.end_date:
                continue
            filtered_rows.append(dict(row))
        return filtered_rows

    @staticmethod
    def _resolve_time_range(
        rows: list[dict[str, object]],
        provider_dimension: str,
        request: MetricSeriesQuery,
    ) -> DatasetTimeRange | None:
        if rows:
            periods = [row[provider_dimension] for row in rows]
            start = min(periods)
            end = max(periods)
            assert isinstance(start, date)
            assert isinstance(end, date)
            return DatasetTimeRange(start=start, end=end)

        if request.start_date is not None and request.end_date is not None:
            return DatasetTimeRange(start=request.start_date, end=request.end_date)
        return None


def build_reporting_provider(
    context: ToolRuntimeContext,
    config: ReportingToolConfig,
) -> ReportingProvider:
    """Create the configured reporting provider implementation."""

    if config.provider == "fixture":
        return FixtureReportingProvider(context=context, config=config)

    raise MCPToolConfigurationError(
        f"Unsupported reporting provider {config.provider!r}."
    )