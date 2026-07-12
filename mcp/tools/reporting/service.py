"""Provider-backed service implementation for the reporting MCP tool."""

from __future__ import annotations

import asyncio
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import hashlib
import json
from threading import Lock
from time import perf_counter
from typing import Protocol

import httpx

from app.context import ToolRuntimeContext
from app.security.arguments import assert_no_secret_like_arguments
from app.observability.events import (
    MCP_REPORTING_PROVIDER_CALL_COMPLETED,
    MCP_REPORTING_PROVIDER_CALL_FAILED,
    MCP_REPORTING_PROVIDER_CALL_STARTED,
    MCP_REPORTING_QUERY_STARTED,
    MCP_REPORTING_REQUEST_VALIDATED,
    MCP_REPORTING_RESULT_NORMALIZED,
    MCP_REPORTING_RESULT_TRUNCATED,
)
from app.observability.logging import emit_observability_event
from app.tools_base.dataset_models import (
    DatasetColumn,
    DatasetTimeRange,
    MetricSeriesQuery,
    StructuredDatasetResponse,
    build_metric_series_query_summary,
    bound_text,
)
from app.tools_base.dataset_validation import (
    DatasetTransportLimits,
    measure_json_bytes,
    normalize_structured_dataset_result,
)

from tools.reporting.models import ReportingToolConfig, load_reporting_tool_config
from tools.reporting.providers import (
    ReportingProvider,
    ReportingProviderError,
    ReportingValidationError,
    build_reporting_provider,
)


RATE_LIMIT_KEY = "reporting.query_metric_series"
CAPABILITY_NAME = "reporting.metric_series.read"
MAX_WARNING_COUNT = 10


@dataclass(frozen=True, slots=True)
class CachedDataset:
    """One cached reporting dataset plus its expiry timestamp."""

    expires_at: datetime
    dataset: StructuredDatasetResponse


@dataclass(frozen=True, slots=True)
class CircuitState:
    """Tracks retryable provider failures and circuit state."""

    consecutive_failures: int = 0
    opened_until: datetime | None = None


class ReportingRuntimeService(Protocol):
    """Protocol for the reporting service surface used by the plugin."""

    async def query_metric_series(self, request: MetricSeriesQuery) -> StructuredDatasetResponse:
        ...

    def health_payload(self) -> dict[str, object]:
        ...


@dataclass(slots=True)
class ReportingService:
    """Validate, cache, and execute approved reporting queries through one provider."""

    context: ToolRuntimeContext
    config: ReportingToolConfig | None = None
    provider: ReportingProvider | None = None
    _cache: dict[str, CachedDataset] = field(default_factory=dict, init=False, repr=False)
    _cache_lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _circuit_lock: Lock = field(default_factory=Lock, init=False, repr=False)
    _circuit_state: CircuitState = field(default_factory=CircuitState, init=False, repr=False)
    _provider_semaphore: asyncio.Semaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.config is None:
            self.config = load_reporting_tool_config(self.context.tool_config)
        if self.provider is None:
            self.provider = build_reporting_provider(self.context, self.config)
        self._provider_semaphore = asyncio.Semaphore(self.config.max_concurrency)

    async def query_metric_series(self, request: MetricSeriesQuery) -> StructuredDatasetResponse:
        """Return a bounded structured dataset for one approved metric-series query."""

        assert self.config is not None
        assert self.provider is not None
        overall_start = perf_counter()
        self._record_query_started(request)
        try:
            effective_request = self._resolve_request(request)
        except ReportingValidationError as error:
            self._record_validation_failure(error, perf_counter() - overall_start)
            raise

        self._record_request_validated(effective_request)
        trusted_scope = dict(self.provider.trusted_scope)
        self.context.rate_limiter.check(
            self._build_rate_limit_key(trusted_scope=trusted_scope)
        )
        cache_key = self._build_cache_key(effective_request)
        cached_dataset = self._get_cached_dataset(cache_key)
        if cached_dataset is not None:
            self._record_cache_outcome(hit=True)
            emit_observability_event(
                self.context.logger,
                self.context.tracer,
                "mcp.reporting.provider.cache_hit",
                payload={
                    "tool_name": RATE_LIMIT_KEY,
                    "capability_name": CAPABILITY_NAME,
                    "provider": self.config.provider,
                    "row_count": cached_dataset.row_count,
                    "truncated": cached_dataset.truncated,
                },
            )
            self._record_normalized_result(cached_dataset)
            self._record_query_success(perf_counter() - overall_start)
            return cached_dataset
        self._record_cache_outcome(hit=False)
        self._raise_if_circuit_open()

        try:
            async with self._provider_semaphore:
                dataset = await self._execute_provider_query(
                    effective_request,
                    trusted_scope=trusted_scope,
                )
        except asyncio.CancelledError:
            raise
        except ReportingProviderError as error:
            self._record_query_failure(error.code, perf_counter() - overall_start)
            raise

        dataset = self._normalize_dataset_result(effective_request, dataset)
        self._record_normalized_result(dataset)
        self._record_query_success(perf_counter() - overall_start)
        self._store_cached_dataset(cache_key, dataset)
        self.context.logger.info(
            "mcp.tool.reporting.query_metric_series",
            payload={
                "provider": self.config.provider,
                "metric_count": len(effective_request.metric_names),
                "filter_count": len(effective_request.filters),
                "returned_rows": dataset.row_count,
                "truncated": dataset.truncated,
            },
        )
        return dataset

    def health_payload(self) -> dict[str, object]:
        """Return safe bounded health details without provider internals."""

        assert self.config is not None
        assert self.provider is not None
        provider_health = self.provider.health(
            deep=self.config.healthcheck_mode == "provider"
        )
        provider_health_status = self._provider_health_status(provider_health)
        circuit_state = self._current_circuit_state()
        circuit_open = (
            circuit_state.opened_until is not None
            and circuit_state.opened_until > self.context.clock.now()
        )
        status = provider_health_status
        if circuit_open:
            status = "error"
        elif provider_health_status == "ok" and circuit_state.consecutive_failures > 0:
            status = "degraded"
        return {
            "status": status,
            "plugin_loaded": True,
            "tool_name": RATE_LIMIT_KEY,
            "capability_name": CAPABILITY_NAME,
            "provider": self.config.provider,
            "provider_configured": True,
            "provider_health_status": provider_health_status,
            "fixture_dataset": self.config.fixture_dataset,
            "healthcheck_mode": self.config.healthcheck_mode,
            "provider_check": provider_health["provider_check"],
            "last_check_at": self._iso_timestamp(self.context.clock.now()),
            "configured_metrics": len(self.config.enabled_metrics),
            "configured_dimensions": len(self.config.enabled_dimensions),
            "auth_profile_configured": self.config.auth_profile_configured,
            "max_concurrency": self.config.max_concurrency,
            "retry_attempts": self.config.retry_attempts,
            "circuit_breaker_threshold": self.config.circuit_breaker_threshold,
            "circuit_breaker_state": "open" if circuit_open else "closed",
            "consecutive_provider_failures": circuit_state.consecutive_failures,
            "circuit_open_until": (
                self._iso_timestamp(circuit_state.opened_until)
                if circuit_open and circuit_state.opened_until is not None
                else None
            ),
            **{
                key: value
                for key, value in provider_health.items()
                if key not in {"provider", "provider_check"}
            },
        }

    def _resolve_request(self, request: MetricSeriesQuery) -> MetricSeriesQuery:
        assert self.config is not None
        assert self.provider is not None

        try:
            assert_no_secret_like_arguments(
                request.model_dump(mode="json"),
                tool_name=RATE_LIMIT_KEY,
            )
        except ValueError as error:
            raise ReportingValidationError(
                "secret_argument",
                "Reporting queries must not contain credential fields or token-like values.",
                summary="The reporting query contains credential material and was rejected.",
                details={"field": "filters", "value": "redacted"},
            ) from error

        unsupported_metrics = sorted(
            set(request.metric_names) - set(self.config.enabled_metrics)
        )
        if unsupported_metrics:
            metric_text = ", ".join(unsupported_metrics)
            raise ReportingValidationError(
                "unsupported_metric",
                f"Metric '{unsupported_metrics[0]}' is not enabled for reporting queries."
                if len(unsupported_metrics) == 1
                else f"Metrics {metric_text} are not enabled for reporting queries.",
                summary="The requested metric is not approved for visualization queries.",
                details={"field": "metric_names", "value": metric_text},
            )

        if request.dimension not in self.config.enabled_dimensions:
            raise ReportingValidationError(
                "unsupported_dimension",
                f"Dimension '{request.dimension}' is not enabled for reporting queries.",
                summary="The requested dimension is not approved for visualization queries.",
                details={"field": "dimension", "value": request.dimension},
            )

        if request.aggregation != "sum":
            raise ReportingValidationError(
                "invalid_query",
                "The fixture reporting provider only supports 'sum' aggregation in phase 3.",
                summary="The reporting query is not valid for this provider.",
                details={"field": "aggregation", "value": request.aggregation},
            )

        if request.granularity != self.config.default_granularity:
            raise ReportingValidationError(
                "invalid_query",
                "The fixture reporting provider only supports "
                f"{self.config.default_granularity!r} granularity in phase 3.",
                summary="The reporting query is not valid for this provider.",
                details={"field": "granularity", "value": request.granularity},
            )

        if len(request.metric_names) > self.config.maximum_metrics_per_query:
            raise ReportingValidationError(
                "invalid_query",
                "metric_names exceeds maximum_metrics_per_query.",
                summary="The reporting query is not valid for this provider.",
                details={
                    "field": "metric_names",
                    "value": str(len(request.metric_names)),
                },
            )

        if len(request.filters) > self.config.maximum_filters:
            raise ReportingValidationError(
                "invalid_query",
                "filters exceed maximum_filters.",
                summary="The reporting query is not valid for this provider.",
                details={"field": "filters", "value": str(len(request.filters))},
            )

        if request.start_date and request.end_date:
            requested_days = (request.end_date - request.start_date).days + 1
            if requested_days > self.config.max_date_range_days:
                raise ReportingValidationError(
                    "invalid_date_range",
                    "requested date range exceeds max_date_range_days.",
                    summary="The requested date range is outside the approved reporting bounds.",
                    details={"field": "date_range_days", "value": str(requested_days)},
                )

        effective_filters = self._apply_trusted_scope(request.filters)

        return request.model_copy(
            update={
                "filters": effective_filters,
                "limit": min(request.limit, self.config.maximum_rows),
            }
        )

    def _apply_trusted_scope(self, filters: dict[str, object]) -> dict[str, object]:
        assert self.provider is not None

        trusted_scope = dict(self.provider.trusted_scope)
        unsupported_filters = sorted(set(filters) - set(trusted_scope))
        if unsupported_filters:
            filter_text = ", ".join(unsupported_filters)
            raise ReportingValidationError(
                "invalid_query",
                "The fixture reporting provider only supports trusted scope filters "
                "business_unit and currency.",
                summary="The reporting query is not valid for this provider.",
                details={"field": "filters", "value": filter_text},
            )

        effective_filters = dict(filters)
        for key, expected_value in trusted_scope.items():
            actual_value = effective_filters.get(key)
            if actual_value is None:
                effective_filters[key] = expected_value
                continue
            if actual_value != expected_value:
                raise ReportingValidationError(
                    "unauthorized_scope",
                    f"Filter '{key}' cannot override the trusted reporting scope.",
                    summary="The requested reporting scope is not authorized.",
                    details={"field": key, "value": str(actual_value)},
                )
        return effective_filters

    def _build_cache_key(self, request: MetricSeriesQuery) -> str:
        assert self.config is not None

        serialized = json.dumps(
            {
                "provider": self.config.provider,
                "fixture_dataset": self.config.fixture_dataset,
                "request": {
                    "metric_names": list(request.metric_names),
                    "dimension": request.dimension,
                    "start_date": request.start_date.isoformat() if request.start_date else None,
                    "end_date": request.end_date.isoformat() if request.end_date else None,
                    "filters": dict(sorted(request.filters.items())),
                    "aggregation": request.aggregation,
                    "granularity": request.granularity,
                    "sort": request.sort,
                    "limit": request.limit,
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _build_rate_limit_key(self, *, trusted_scope: dict[str, object]) -> str:
        actor = self._request_actor_id()
        scope_fingerprint = hashlib.sha256(
            json.dumps(
                dict(sorted(trusted_scope.items())),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:12]
        return ":".join([RATE_LIMIT_KEY, actor, scope_fingerprint])

    async def _execute_provider_query(
        self,
        request: MetricSeriesQuery,
        *,
        trusted_scope: dict[str, object],
    ) -> StructuredDatasetResponse:
        assert self.config is not None
        assert self.provider is not None

        last_error: ReportingProviderError | None = None
        for attempt in range(1, self.config.retry_attempts + 1):
            provider_start = perf_counter()
            emit_observability_event(
                self.context.logger,
                self.context.tracer,
                MCP_REPORTING_PROVIDER_CALL_STARTED,
                payload={
                    "tool_name": RATE_LIMIT_KEY,
                    "capability_name": CAPABILITY_NAME,
                    "provider": self.config.provider,
                    "timeout_seconds": self.config.timeout_seconds,
                    "attempt": attempt,
                    "retry_attempts": self.config.retry_attempts,
                },
            )
            try:
                async with asyncio.timeout(self.config.timeout_seconds):
                    dataset = await self.provider.query_metric_series(
                        request,
                        trusted_scope=trusted_scope,
                    )
            except asyncio.CancelledError:
                raise
            except ReportingProviderError as error:
                normalized = error
            except asyncio.TimeoutError as error:
                normalized = ReportingProviderError(
                    "timeout",
                    "Reporting provider timed out.",
                    summary="The reporting provider timed out before it returned a dataset.",
                    retryable=True,
                )
                error = normalized
            except Exception as error:
                normalized = self._normalize_provider_error(error)
            else:
                self._record_provider_success(
                    perf_counter() - provider_start,
                    row_count=dataset.row_count,
                )
                self._reset_circuit()
                return dataset

            self._record_provider_failure(normalized.code, perf_counter() - provider_start)
            last_error = normalized
            if not normalized.retryable or attempt >= self.config.retry_attempts:
                self._record_circuit_failure(normalized)
                raise normalized

            await asyncio.sleep(0)

        assert last_error is not None
        raise last_error

    def _raise_if_circuit_open(self) -> None:
        circuit_state = self._current_circuit_state()
        if circuit_state.opened_until is None:
            return
        if circuit_state.opened_until <= self.context.clock.now():
            self._reset_circuit()
            return
        raise ReportingProviderError(
            "provider_unavailable",
            "Reporting provider is temporarily unavailable after repeated failures.",
            summary="The reporting provider is temporarily unavailable and the tool is waiting before retrying it.",
            retryable=True,
        )

    def _record_circuit_failure(self, error: ReportingProviderError) -> None:
        assert self.config is not None

        if not error.retryable:
            return

        with self._circuit_lock:
            failures = self._circuit_state.consecutive_failures + 1
            opened_until = self._circuit_state.opened_until
            if failures >= self.config.circuit_breaker_threshold:
                opened_until = self.context.clock.now() + timedelta(
                    seconds=self.config.circuit_breaker_reset_seconds
                )
            self._circuit_state = CircuitState(
                consecutive_failures=failures,
                opened_until=opened_until,
            )

    def _reset_circuit(self) -> None:
        with self._circuit_lock:
            self._circuit_state = CircuitState()

    def _current_circuit_state(self) -> CircuitState:
        with self._circuit_lock:
            return CircuitState(
                consecutive_failures=self._circuit_state.consecutive_failures,
                opened_until=self._circuit_state.opened_until,
            )

    def _request_actor_id(self) -> str:
        if self.context.auth is None:
            return "anonymous"

        try:
            request_context = self.context.auth.current_request_context(require_authenticated=False)
        except Exception:
            return "anonymous"

        for candidate in (
            getattr(request_context, "auth_subject", None),
            getattr(request_context, "caller_service", None),
            getattr(request_context, "request_id", None),
        ):
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip().replace(":", "_")
        return "anonymous"

    def _get_cached_dataset(self, cache_key: str) -> StructuredDatasetResponse | None:
        assert self.config is not None

        if self.config.cache_ttl_seconds <= 0:
            return None

        now = self.context.clock.now()
        with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                del self._cache[cache_key]
                return None

        return entry.dataset.model_copy(deep=True)

    def _store_cached_dataset(self, cache_key: str, dataset: StructuredDatasetResponse) -> None:
        assert self.config is not None

        if self.config.cache_ttl_seconds <= 0:
            return

        expires_at = self.context.clock.now() + timedelta(seconds=self.config.cache_ttl_seconds)
        with self._cache_lock:
            self._cache[cache_key] = CachedDataset(
                expires_at=expires_at,
                dataset=dataset.model_copy(deep=True),
            )

    def _record_query_started(self, request: MetricSeriesQuery) -> None:
        tags = self._metric_tags(status="attempt")
        self.context.metrics.increment("mcp.reporting.query.call.count", tags)
        emit_observability_event(
            self.context.logger,
            self.context.tracer,
            MCP_REPORTING_QUERY_STARTED,
            payload={
                "tool_name": RATE_LIMIT_KEY,
                "capability_name": CAPABILITY_NAME,
                "dimension": request.dimension,
                "metric_count": len(request.metric_names),
                "filter_count": len(request.filters),
                "requested_limit": request.limit,
                "aggregation": request.aggregation,
                "granularity": request.granularity,
                "has_start_date": request.start_date is not None,
                "has_end_date": request.end_date is not None,
                "sort": request.sort,
            },
        )

    def _record_request_validated(self, request: MetricSeriesQuery) -> None:
        emit_observability_event(
            self.context.logger,
            self.context.tracer,
            MCP_REPORTING_REQUEST_VALIDATED,
            payload={
                "tool_name": RATE_LIMIT_KEY,
                "capability_name": CAPABILITY_NAME,
                "dimension": request.dimension,
                "metric_count": len(request.metric_names),
                "filter_count": len(request.filters),
                "effective_limit": request.limit,
                "aggregation": request.aggregation,
                "granularity": request.granularity,
                "provider": self.config.provider,
            },
        )

    def _record_cache_outcome(self, *, hit: bool) -> None:
        assert self.config is not None

        if self.config.cache_ttl_seconds <= 0:
            return

        self.context.metrics.increment(
            "mcp.reporting.query.cache.hit.count" if hit else "mcp.reporting.query.cache.miss.count",
            self._metric_tags(status="ok"),
        )

    def _record_query_success(self, duration_seconds: float) -> None:
        duration_ms = round(duration_seconds * 1000, 3)
        self.context.metrics.timing(
            "mcp.reporting.query.duration_ms",
            duration_ms,
            self._metric_tags(status="ok"),
        )

    def _record_query_failure(self, error_code: str, duration_seconds: float) -> None:
        duration_ms = round(duration_seconds * 1000, 3)
        tags = self._metric_tags(status="error", error_code=error_code)
        self.context.metrics.increment("mcp.reporting.query.failure.count", tags)
        self.context.metrics.timing("mcp.reporting.query.duration_ms", duration_ms, tags)
        if error_code == "timeout":
            self.context.metrics.increment("mcp.reporting.query.provider_timeout.count", tags)
        if error_code == "rate_limited":
            self.context.metrics.increment("mcp.reporting.query.provider_rate_limited.count", tags)

    def _record_validation_failure(
        self,
        error: ReportingValidationError,
        duration_seconds: float,
    ) -> None:
        duration_ms = round(duration_seconds * 1000, 3)
        tags = self._metric_tags(status="error", error_code=error.code)
        self.context.metrics.increment("mcp.reporting.query.failure.count", tags)
        self.context.metrics.increment("mcp.reporting.query.invalid.count", tags)
        self.context.metrics.timing("mcp.reporting.query.duration_ms", duration_ms, tags)

    def _record_provider_success(self, duration_seconds: float, *, row_count: int) -> None:
        duration_ms = round(duration_seconds * 1000, 3)
        tags = self._metric_tags(status="ok")
        self.context.metrics.increment("mcp.reporting.provider.call.count", tags)
        self.context.metrics.timing("mcp.reporting.provider.duration_ms", duration_ms, tags)
        emit_observability_event(
            self.context.logger,
            self.context.tracer,
            MCP_REPORTING_PROVIDER_CALL_COMPLETED,
            payload={
                "tool_name": RATE_LIMIT_KEY,
                "capability_name": CAPABILITY_NAME,
                "provider": self.config.provider,
                "status": "ok",
                "duration_ms": duration_ms,
                "row_count": row_count,
            },
        )

    def _record_provider_failure(self, error_code: str, duration_seconds: float) -> None:
        duration_ms = round(duration_seconds * 1000, 3)
        tags = self._metric_tags(status="error", error_code=error_code)
        self.context.metrics.increment("mcp.reporting.provider.call.count", tags)
        self.context.metrics.increment("mcp.reporting.provider.error.count", tags)
        self.context.metrics.timing("mcp.reporting.provider.duration_ms", duration_ms, tags)
        emit_observability_event(
            self.context.logger,
            self.context.tracer,
            MCP_REPORTING_PROVIDER_CALL_FAILED,
            payload={
                "tool_name": RATE_LIMIT_KEY,
                "capability_name": CAPABILITY_NAME,
                "provider": self.config.provider,
                "status": "error",
                "error_code": error_code,
                "duration_ms": duration_ms,
            },
            level="warning",
        )

    def _record_normalized_result(self, dataset: StructuredDatasetResponse) -> None:
        dataset_bytes = measure_json_bytes(dataset.model_dump(mode="json"))
        tags = self._metric_tags(status="ok")
        self.context.metrics.timing(
            "mcp.reporting.query.returned_rows",
            float(dataset.row_count),
            tags,
        )
        self.context.metrics.timing(
            "mcp.reporting.query.serialized_bytes",
            float(dataset_bytes),
            tags,
        )
        emit_observability_event(
            self.context.logger,
            self.context.tracer,
            MCP_REPORTING_RESULT_NORMALIZED,
            payload={
                "tool_name": RATE_LIMIT_KEY,
                "capability_name": CAPABILITY_NAME,
                "row_count": dataset.row_count,
                "total_row_count": dataset.total_row_count,
                "truncated": dataset.truncated,
                "warning_count": len(dataset.warnings),
                "serialized_bytes": dataset_bytes,
            },
        )
        if dataset.truncated:
            self.context.metrics.increment("mcp.reporting.query.truncation.count", tags)
            emit_observability_event(
                self.context.logger,
                self.context.tracer,
                MCP_REPORTING_RESULT_TRUNCATED,
                payload={
                    "tool_name": RATE_LIMIT_KEY,
                    "capability_name": CAPABILITY_NAME,
                    "row_count": dataset.row_count,
                    "total_row_count": dataset.total_row_count,
                    "reasons": self._truncation_reasons(dataset),
                },
            )

    def _normalize_dataset_result(
        self,
        request: MetricSeriesQuery,
        dataset: StructuredDatasetResponse,
    ) -> StructuredDatasetResponse:
        assert self.config is not None

        dimension_column = self._resolve_dimension_column(dataset, request.dimension)
        metric_columns = [column for column in dataset.columns if column.semantic_role == "metric"]
        normalized_rows, duplicate_dimension_values = self._aggregate_and_sort_rows(
            rows=dataset.rows,
            request=request,
            dimension_column=dimension_column,
            metric_columns=metric_columns,
        )
        normalized_total_row_count = len(normalized_rows)
        provider_partial = dataset.truncated or (
            dataset.total_row_count is not None and dataset.total_row_count > dataset.row_count
        )

        warnings = list(dataset.warnings)
        if duplicate_dimension_values:
            warnings.append(
                f"Duplicate {request.dimension} values were aggregated before the result was returned."
            )

        missing_bucket_count = self._count_missing_time_buckets(
            rows=normalized_rows,
            request=request,
            dimension_column=dimension_column,
        )
        if missing_bucket_count > 0:
            warnings.append(
                f"Time-series data is missing {missing_bucket_count} {request.granularity} bucket(s) within the applied range."
            )

        if self._contains_null_metric_values(normalized_rows, metric_columns):
            warnings.append("Result contains null values for one or more chart fields.")

        if self._provider_flag(dataset.provenance, names=("rounded_data", "provider_rounded", "rounded")):
            warnings.append("Provider data was rounded before the dataset was returned.")

        if provider_partial or self._provider_flag(
            dataset.provenance,
            names=("partial_data", "provider_partial_data", "partial"),
        ):
            warnings.append("Provider returned partial data for the approved query.")

        if normalized_total_row_count == 0:
            warnings.append("No reporting data matched the approved query range.")

        selected_rows = normalized_rows[: request.limit]
        truncated = provider_partial or len(selected_rows) < normalized_total_row_count
        total_row_count = (
            max(normalized_total_row_count, dataset.total_row_count or normalized_total_row_count)
            if provider_partial
            else normalized_total_row_count
        )

        if len(selected_rows) < normalized_total_row_count:
            warnings.append(
                f"Result truncated to {len(selected_rows)} rows to honor the effective row limit."
            )

        if (
            dimension_column.semantic_role in {"category", "dimension"}
            and normalized_total_row_count > len(selected_rows)
        ):
            warnings.append(
                f"High {request.dimension} cardinality was truncated to the approved row limit."
            )

        time_range = self._resolve_dataset_time_range(
            rows=normalized_rows,
            request=request,
            dimension_column=dimension_column,
        )
        provenance = self._build_provenance(
            request=request,
            dataset=dataset,
            time_range=time_range,
            provider_partial=provider_partial,
        )

        normalized_dataset = self._build_dataset_response(
            template=dataset,
            request=request,
            rows=selected_rows,
            total_row_count=total_row_count,
            truncated=truncated,
            warnings=warnings,
            time_range=time_range,
            provenance=provenance,
        )
        return self._fit_dataset_to_transport_limit(
            request=request,
            template=dataset,
            rows=selected_rows,
            total_row_count=total_row_count,
            truncated=truncated,
            warnings=warnings,
            time_range=time_range,
            provenance=provenance,
            dataset=normalized_dataset,
        )

    @staticmethod
    def _resolve_dimension_column(
        dataset: StructuredDatasetResponse,
        dimension_name: str,
    ) -> DatasetColumn:
        for column in dataset.columns:
            if column.name == dimension_name:
                return column
        raise ReportingProviderError(
            "schema_mismatch",
            f"Reporting provider did not return the requested dimension {dimension_name!r}.",
            summary="The reporting provider returned an invalid dataset shape.",
        )

    def _aggregate_and_sort_rows(
        self,
        *,
        rows: list[dict[str, object]],
        request: MetricSeriesQuery,
        dimension_column: DatasetColumn,
        metric_columns: list[DatasetColumn],
    ) -> tuple[list[dict[str, object]], bool]:
        grouped_rows: dict[object, dict[str, object]] = {}
        duplicate_dimension_values = False

        for row in rows:
            dimension_value = row.get(request.dimension)
            if dimension_value not in grouped_rows:
                grouped_rows[dimension_value] = dict(row)
                continue

            duplicate_dimension_values = True
            existing = grouped_rows[dimension_value]
            for metric_column in metric_columns:
                metric_name = metric_column.name
                existing[metric_name] = self._aggregate_metric_values(
                    existing.get(metric_name),
                    row.get(metric_name),
                    metric_column=metric_column,
                )

        sorted_rows = sorted(
            grouped_rows.values(),
            key=lambda row: self._row_sort_key(
                row.get(request.dimension),
                data_type=dimension_column.data_type,
                row=row,
            ),
            reverse=request.sort == "desc",
        )
        return sorted_rows, duplicate_dimension_values

    @staticmethod
    def _aggregate_metric_values(
        left: object,
        right: object,
        *,
        metric_column: DatasetColumn,
    ) -> object:
        numeric_values = [
            value
            for value in (left, right)
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        if not numeric_values:
            return None

        total = sum(float(value) for value in numeric_values)
        if metric_column.data_type == "integer":
            return int(total)
        return float(total)

    def _count_missing_time_buckets(
        self,
        *,
        rows: list[dict[str, object]],
        request: MetricSeriesQuery,
        dimension_column: DatasetColumn,
    ) -> int:
        if dimension_column.data_type not in {"date", "datetime"} or not rows:
            return 0
        if request.granularity == "category":
            return 0

        actual_dates = {
            self._parse_date_value(row[request.dimension], data_type=dimension_column.data_type)
            for row in rows
        }
        first_bucket = min(actual_dates)
        last_bucket = max(actual_dates)
        start = self._bucket_floor(request.start_date or first_bucket, request.granularity)
        end = self._bucket_floor(request.end_date or last_bucket, request.granularity)

        missing = 0
        current = start
        while current <= end:
            if current not in actual_dates:
                missing += 1
            current = self._advance_bucket(current, request.granularity)
        return missing

    @staticmethod
    def _contains_null_metric_values(
        rows: list[dict[str, object]],
        metric_columns: list[DatasetColumn],
    ) -> bool:
        return any(row.get(metric_column.name) is None for row in rows for metric_column in metric_columns)

    @staticmethod
    def _provider_flag(
        provenance: dict[str, object],
        *,
        names: tuple[str, ...],
    ) -> bool:
        return any(provenance.get(name) is True for name in names)

    def _resolve_dataset_time_range(
        self,
        *,
        rows: list[dict[str, object]],
        request: MetricSeriesQuery,
        dimension_column: DatasetColumn,
    ) -> DatasetTimeRange | None:
        if dimension_column.data_type not in {"date", "datetime"}:
            return None

        if rows:
            start_bucket = self._bucket_floor(
                self._parse_date_value(rows[0][request.dimension], data_type=dimension_column.data_type),
                request.granularity,
            )
            end_bucket_start = self._bucket_floor(
                self._parse_date_value(rows[-1][request.dimension], data_type=dimension_column.data_type),
                request.granularity,
            )
            return DatasetTimeRange(
                start=start_bucket,
                end=self._bucket_end(end_bucket_start, request.granularity),
            )

        if request.start_date is not None and request.end_date is not None:
            return DatasetTimeRange(
                start=self._bucket_floor(request.start_date, request.granularity),
                end=self._bucket_end(request.end_date, request.granularity),
            )
        return None

    def _build_provenance(
        self,
        *,
        request: MetricSeriesQuery,
        dataset: StructuredDatasetResponse,
        time_range: DatasetTimeRange | None,
        provider_partial: bool,
    ) -> dict[str, object]:
        base_entries: list[tuple[str, object]] = []
        existing = dataset.provenance

        for key in ("provider", "tool_name", "fixture_dataset", "metric_count", "filter_count"):
            if key in existing and existing[key] is not None:
                base_entries.append((key, existing[key]))

        base_entries.extend(
            [
                ("provider", self.config.provider),
                ("tool_name", RATE_LIMIT_KEY),
                ("aggregation", request.aggregation),
                ("granularity", request.granularity),
            ]
        )
        if time_range is not None:
            base_entries.append(("applied_start_date", time_range.start.isoformat()))
            base_entries.append(("applied_end_date", time_range.end.isoformat()))
            base_entries.append(
                (
                    "data_freshness_timestamp",
                    f"{time_range.end.isoformat()}T23:59:59Z",
                )
            )
        else:
            base_entries.append(
                (
                    "data_freshness_timestamp",
                    self.context.clock.now().isoformat().replace("+00:00", "Z"),
                )
            )

        if provider_partial:
            base_entries.append(("partial_data", True))
        if self._provider_flag(existing, names=("rounded_data", "provider_rounded", "rounded")):
            base_entries.append(("rounded_data", True))

        normalized: dict[str, object] = {}
        for key, value in base_entries:
            if value is None:
                continue
            normalized[key] = value
            if len(normalized) >= 12:
                break
        return normalized

    def _build_dataset_response(
        self,
        *,
        template: StructuredDatasetResponse,
        request: MetricSeriesQuery,
        rows: list[dict[str, object]],
        total_row_count: int,
        truncated: bool,
        warnings: list[str],
        time_range: DatasetTimeRange | None,
        provenance: dict[str, object],
    ) -> StructuredDatasetResponse:
        deduplicated_warnings = self._normalize_warnings(warnings)
        resolved_total_row_count = total_row_count if truncated else len(rows)
        return StructuredDatasetResponse(
            dataset_id=template.dataset_id,
            columns=template.columns,
            rows=rows,
            row_count=len(rows),
            total_row_count=resolved_total_row_count,
            truncated=truncated,
            source=template.source,
            query_summary=build_metric_series_query_summary(
                request,
                row_count=len(rows),
                truncated=truncated,
            ),
            time_range=time_range,
            warnings=deduplicated_warnings,
            provenance=provenance,
        )

    def _fit_dataset_to_transport_limit(
        self,
        *,
        request: MetricSeriesQuery,
        template: StructuredDatasetResponse,
        rows: list[dict[str, object]],
        total_row_count: int,
        truncated: bool,
        warnings: list[str],
        time_range: DatasetTimeRange | None,
        provenance: dict[str, object],
        dataset: StructuredDatasetResponse,
    ) -> StructuredDatasetResponse:
        assert self.config is not None

        transport_limits = DatasetTransportLimits(max_result_bytes=self.config.max_result_bytes)
        candidate_rows = list(rows)
        transport_truncated = False
        while True:
            transport_warnings = list(warnings)
            if transport_truncated:
                transport_warnings.append(
                    f"Result truncated to {len(candidate_rows)} rows to honor the MCP transport size limit."
                )
            candidate = self._build_dataset_response(
                template=template,
                request=request,
                rows=candidate_rows,
                total_row_count=total_row_count,
                truncated=truncated or transport_truncated,
                warnings=transport_warnings,
                time_range=time_range,
                provenance=provenance,
            )
            try:
                normalize_structured_dataset_result(
                    tool_name=RATE_LIMIT_KEY,
                    dataset=candidate,
                    limits=transport_limits,
                )
                return candidate
            except ValueError as error:
                if "max_result_bytes" not in str(error):
                    raise
                if not candidate_rows:
                    raise
                transport_truncated = True
                candidate_rows = candidate_rows[:-1]

    @staticmethod
    def _metric_tags(
        *,
        status: str,
        error_code: str | None = None,
    ) -> dict[str, str]:
        tags = {
            "tool_name": RATE_LIMIT_KEY,
            "capability_name": CAPABILITY_NAME,
            "status": status,
        }
        if error_code is not None:
            tags["error_code"] = error_code
        return tags

    @staticmethod
    def _provider_health_status(provider_health: dict[str, object]) -> str:
        provider_check = str(provider_health.get("provider_check") or "ok").lower()
        if provider_check in {"error", "failed", "unhealthy"}:
            return "error"
        if provider_check in {"degraded", "warning"}:
            return "degraded"
        return "ok"

    @staticmethod
    def _iso_timestamp(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _truncation_reasons(dataset: StructuredDatasetResponse) -> list[str]:
        reasons: list[str] = []
        warning_text = " ".join(dataset.warnings).lower()
        if "transport size limit" in warning_text:
            reasons.append("transport_limit")
        if "row limit" in warning_text or (
            dataset.total_row_count is not None and dataset.total_row_count > dataset.row_count
        ):
            reasons.append("row_limit")
        if "partial data" in warning_text:
            reasons.append("provider_partial")
        if not reasons:
            reasons.append("bounded_result")
        return reasons

    @staticmethod
    def _normalize_warnings(warnings: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for warning in warnings:
            cleaned = bound_text(str(warning), max_chars=200)
            lowered = cleaned.lower()
            if lowered in seen:
                continue
            normalized.append(cleaned)
            seen.add(lowered)
            if len(normalized) >= MAX_WARNING_COUNT:
                break
        return normalized

    @staticmethod
    def _row_sort_key(value: object, *, data_type: str, row: dict[str, object]) -> tuple[object, str]:
        if value is None:
            return ("", json.dumps(row, sort_keys=True, default=str, separators=(",", ":")))

        if data_type == "date":
            normalized_value: object = date.fromisoformat(str(value))
        elif data_type == "datetime":
            normalized_value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        else:
            normalized_value = value
        return (
            normalized_value,
            json.dumps(row, sort_keys=True, default=str, separators=(",", ":")),
        )

    @staticmethod
    def _parse_date_value(value: object, *, data_type: str) -> date:
        if data_type == "datetime":
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
        return date.fromisoformat(str(value))

    @staticmethod
    def _bucket_floor(value: date, granularity: str) -> date:
        if granularity == "day":
            return value
        if granularity == "week":
            return value - timedelta(days=value.weekday())
        if granularity == "month":
            return value.replace(day=1)
        if granularity == "quarter":
            quarter_month = ((value.month - 1) // 3) * 3 + 1
            return value.replace(month=quarter_month, day=1)
        if granularity == "year":
            return value.replace(month=1, day=1)
        return value

    def _bucket_end(self, value: date, granularity: str) -> date:
        bucket_start = self._bucket_floor(value, granularity)
        if granularity == "day":
            return bucket_start
        if granularity == "week":
            return bucket_start + timedelta(days=6)
        if granularity == "month":
            return bucket_start.replace(day=monthrange(bucket_start.year, bucket_start.month)[1])
        if granularity == "quarter":
            next_bucket = self._advance_bucket(bucket_start, granularity)
            return next_bucket - timedelta(days=1)
        if granularity == "year":
            return bucket_start.replace(month=12, day=31)
        return bucket_start

    @staticmethod
    def _advance_bucket(value: date, granularity: str) -> date:
        if granularity == "day":
            return value + timedelta(days=1)
        if granularity == "week":
            return value + timedelta(days=7)
        if granularity == "month":
            year = value.year + (1 if value.month == 12 else 0)
            month = 1 if value.month == 12 else value.month + 1
            return value.replace(year=year, month=month, day=1)
        if granularity == "quarter":
            month = value.month + 3
            year = value.year + ((month - 1) // 12)
            month = ((month - 1) % 12) + 1
            return value.replace(year=year, month=month, day=1)
        if granularity == "year":
            return value.replace(year=value.year + 1, month=1, day=1)
        return value

    @staticmethod
    def _normalize_provider_error(error: Exception) -> ReportingProviderError:
        error_type = error.__class__.__name__.lower()
        message = str(error)
        normalized_message = message.lower()

        if isinstance(error, httpx.TimeoutException) or "timeout" in error_type:
            return ReportingProviderError(
                "timeout",
                "Reporting provider timed out.",
                summary="The reporting provider timed out before it returned a dataset.",
                retryable=True,
            )

        if "429" in message or "rate" in normalized_message:
            return ReportingProviderError(
                "rate_limited",
                "Reporting provider rate limited the request.",
                summary="The reporting provider rate limited the request.",
                retryable=True,
            )

        if isinstance(error, (httpx.HTTPError, OSError)):
            return ReportingProviderError(
                "provider_unavailable",
                "Reporting provider is unavailable.",
                summary="The reporting provider is unavailable right now.",
                retryable=True,
            )

        if isinstance(error, ValueError):
            return ReportingProviderError(
                "schema_mismatch",
                "Reporting provider returned data that does not match the visualization dataset contract.",
                summary="The reporting provider returned an invalid dataset shape.",
                retryable=False,
            )

        return ReportingProviderError(
            "internal_error",
            "Reporting provider request failed.",
            summary="The reporting provider request failed.",
            retryable=False,
        )
