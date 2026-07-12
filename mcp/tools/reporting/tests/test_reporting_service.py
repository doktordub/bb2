import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from app.bootstrap import bootstrap
from app.observability.context import build_trace_context, trace_context_scope
from app.observability.events import (
    MCP_REPORTING_PROVIDER_CALL_COMPLETED,
    MCP_REPORTING_PROVIDER_CALL_STARTED,
    MCP_REPORTING_QUERY_STARTED,
    MCP_REPORTING_REQUEST_VALIDATED,
    MCP_REPORTING_RESULT_NORMALIZED,
    MCP_REPORTING_RESULT_TRUNCATED,
)
from app.observability.metrics import InMemoryMetricsRecorder
from app.observability.tracing import InMemoryTraceRecorder
from app.security.redaction import Redactor
import pytest

from app.tools_base.dataset_models import DatasetColumn, MetricSeriesQuery, StructuredDatasetResponse
from app.tools_base.validation import load_manifest, load_tool_config
from tests.unit.observability.support import build_tool_context

from tools.reporting.models import load_reporting_tool_config
from tools.reporting.providers import ReportingProviderError, ReportingValidationError
from tools.reporting.service import CAPABILITY_NAME, RATE_LIMIT_KEY, ReportingService


REPORTING_TOOL_DIR = Path(__file__).resolve().parents[1]


def _build_service(*, config_overrides: dict[str, object] | None = None) -> ReportingService:
    runtime = bootstrap()
    manifest = load_manifest(REPORTING_TOOL_DIR / "manifest.yaml")
    raw_config = load_tool_config(REPORTING_TOOL_DIR / "config.yaml")
    if config_overrides:
        raw_config.update(config_overrides)
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=raw_config,
    )
    return ReportingService(context, config=load_reporting_tool_config(raw_config))


class StubReportingProvider:
    def __init__(
        self,
        dataset: StructuredDatasetResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.dataset = dataset
        self.error = error
        self.calls: list[dict[str, object]] = []

    @property
    def trusted_scope(self) -> dict[str, object]:
        return {"business_unit": "core", "currency": "USD"}

    async def query_metric_series(self, request, *, trusted_scope):
        self.calls.append(
            {
                "request": request,
                "trusted_scope": dict(trusted_scope),
            }
        )
        if self.error is not None:
            raise self.error
        assert self.dataset is not None
        return self.dataset.model_copy(deep=True)

    async def query_category_summary(self, request, *, trusted_scope):
        del request, trusted_scope
        raise NotImplementedError

    def health(self, *, deep: bool = False) -> dict[str, object]:
        return {
            "provider": "fixture",
            "provider_check": "fixture" if deep else "skipped",
        }


def _build_service_with_provider(provider: StubReportingProvider) -> ReportingService:
    runtime = bootstrap()
    manifest = load_manifest(REPORTING_TOOL_DIR / "manifest.yaml")
    raw_config = load_tool_config(REPORTING_TOOL_DIR / "config.yaml")
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=raw_config,
    )
    return ReportingService(
        context,
        config=load_reporting_tool_config(raw_config),
        provider=provider,
    )


class FlakyReportingProvider(StubReportingProvider):
    def __init__(self, dataset: StructuredDatasetResponse) -> None:
        super().__init__(dataset=dataset)
        self.failures_remaining = 1

    async def query_metric_series(self, request, *, trusted_scope):
        self.calls.append(
            {
                "request": request,
                "trusted_scope": dict(trusted_scope),
            }
        )
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise ReportingProviderError(
                "provider_unavailable",
                "Reporting provider is unavailable.",
                summary="The reporting provider is unavailable right now.",
                retryable=True,
            )
        assert self.dataset is not None
        return self.dataset.model_copy(deep=True)


class AlwaysRetryableProvider(StubReportingProvider):
    async def query_metric_series(self, request, *, trusted_scope):
        self.calls.append(
            {
                "request": request,
                "trusted_scope": dict(trusted_scope),
            }
        )
        raise ReportingProviderError(
            "provider_unavailable",
            "Reporting provider is unavailable.",
            summary="The reporting provider is unavailable right now.",
            retryable=True,
        )


class ConcurrencyTrackingProvider(StubReportingProvider):
    def __init__(self, dataset: StructuredDatasetResponse) -> None:
        super().__init__(dataset=dataset)
        self.in_flight = 0
        self.max_in_flight = 0

    async def query_metric_series(self, request, *, trusted_scope):
        self.calls.append(
            {
                "request": request,
                "trusted_scope": dict(trusted_scope),
            }
        )
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert self.dataset is not None
            return self.dataset.model_copy(deep=True)
        finally:
            self.in_flight -= 1


class RecordingRateLimiter:
    mode_name = "recording"

    def __init__(self) -> None:
        self.keys: list[str] = []

    def check(self, key: str) -> None:
        self.keys.append(key)


class StubAuthService:
    enabled = True
    mode_name = "bearer"

    def build_auth_provider(self, *, base_url: str | None):
        del base_url
        return None

    def current_request_context(self, *, require_authenticated: bool = False):
        del require_authenticated
        return SimpleNamespace(
            auth_subject="chart-agent",
            caller_service="backend",
            request_id="request-123",
        )


async def test_reporting_service_returns_structured_dataset_for_supported_fixture_query() -> None:
    service = _build_service()
    dataset = await service.query_metric_series(
        MetricSeriesQuery(
            metric_names=["income", "expense"],
            dimension="reporting_period",
            start_date="2026-01-01",
            end_date="2026-06-30",
            filters={"currency": "USD", "business_unit": "core"},
            aggregation="sum",
            granularity="month",
            sort="asc",
            limit=6,
        )
    )

    assert dataset.row_count == 6
    assert dataset.total_row_count == 6
    assert dataset.truncated is False
    assert [column.name for column in dataset.columns] == [
        "reporting_period",
        "income",
        "expense",
    ]
    assert dataset.provenance["provider"] == "fixture"
    assert dataset.provenance["data_freshness_timestamp"] == "2026-06-30T23:59:59Z"
    assert dataset.time_range is not None
    assert dataset.time_range.model_dump(mode="json") == {
        "start": "2026-01-01",
        "end": "2026-06-30",
    }


async def test_reporting_service_clamps_limit_and_marks_truncation() -> None:
    service = _build_service()
    dataset = await service.query_metric_series(
        MetricSeriesQuery(
            metric_names=["income"],
            dimension="reporting_period",
            granularity="month",
            limit=2,
        )
    )

    assert dataset.row_count == 2
    assert dataset.total_row_count == 6
    assert dataset.truncated is True
    assert dataset.time_range is not None
    assert dataset.time_range.model_dump(mode="json") == {
        "start": "2026-01-01",
        "end": "2026-06-30",
    }
    assert dataset.warnings == [
        "Result truncated to 2 rows to honor the effective row limit."
    ]


async def test_reporting_service_rejects_unsupported_metrics_before_provider_access() -> None:
    service = _build_service()

    with pytest.raises(ReportingValidationError) as error:
        await service.query_metric_series(
            MetricSeriesQuery(
                metric_names=["profit"],
                dimension="reporting_period",
                granularity="month",
                limit=1,
            )
        )

    assert error.value.code == "unsupported_metric"


async def test_reporting_service_rejects_sql_like_metric_names() -> None:
    service = _build_service()

    with pytest.raises(ReportingValidationError) as error:
        await service.query_metric_series(
            MetricSeriesQuery(
                metric_names=["select revenue from ledger"],
                dimension="reporting_period",
                granularity="month",
                limit=1,
            )
        )

    assert error.value.code == "unsupported_metric"


async def test_reporting_service_rejects_unknown_dimensions() -> None:
    service = _build_service()

    with pytest.raises(ReportingValidationError) as error:
        await service.query_metric_series(
            MetricSeriesQuery(
                metric_names=["income"],
                dimension="profit_center",
                granularity="month",
                limit=1,
            )
        )

    assert error.value.code == "unsupported_dimension"


async def test_reporting_service_rejects_excessive_filters() -> None:
    service = _build_service(config_overrides={"maximum_filters": 1})

    with pytest.raises(ReportingValidationError) as error:
        await service.query_metric_series(
            MetricSeriesQuery(
                metric_names=["income"],
                dimension="reporting_period",
                granularity="month",
                filters={"business_unit": "core", "currency": "USD"},
                limit=1,
            )
        )

    assert error.value.code == "invalid_query"


async def test_reporting_service_rejects_excessive_date_ranges() -> None:
    service = _build_service(config_overrides={"max_date_range_days": 30})

    with pytest.raises(ReportingValidationError) as error:
        await service.query_metric_series(
            MetricSeriesQuery(
                metric_names=["income"],
                dimension="reporting_period",
                start_date="2026-01-01",
                end_date="2026-03-31",
                granularity="month",
                limit=1,
            )
        )

    assert error.value.code == "invalid_date_range"


async def test_reporting_service_rejects_cross_scope_filters() -> None:
    service = _build_service()

    with pytest.raises(ReportingValidationError) as error:
        await service.query_metric_series(
            MetricSeriesQuery(
                metric_names=["income"],
                dimension="reporting_period",
                granularity="month",
                filters={"business_unit": "other", "currency": "USD"},
                limit=1,
            )
        )

    assert error.value.code == "unauthorized_scope"


async def test_reporting_service_applies_trusted_scope_and_caches_successful_results() -> None:
    fixture_service = _build_service()
    fixture_dataset = await fixture_service.query_metric_series(
        MetricSeriesQuery(
            metric_names=["income"],
            dimension="reporting_period",
            granularity="month",
            limit=2,
        )
    )

    provider = StubReportingProvider(dataset=fixture_dataset)
    service = _build_service_with_provider(provider)

    first = await service.query_metric_series(
        MetricSeriesQuery(
            metric_names=["income"],
            dimension="reporting_period",
            granularity="month",
            limit=2,
        )
    )
    second = await service.query_metric_series(
        MetricSeriesQuery(
            metric_names=["income"],
            dimension="reporting_period",
            granularity="month",
            limit=2,
        )
    )

    assert len(provider.calls) == 1
    recorded_request = provider.calls[0]["request"]
    assert recorded_request.filters == {
        "business_unit": "core",
        "currency": "USD",
    }
    assert first == second


async def test_reporting_service_normalizes_provider_errors() -> None:
    provider = StubReportingProvider(error=OSError("upstream unavailable"))
    service = _build_service_with_provider(provider)

    with pytest.raises(ReportingProviderError) as error:
        await service.query_metric_series(
            MetricSeriesQuery(
                metric_names=["income"],
                dimension="reporting_period",
                granularity="month",
                limit=1,
            )
        )

    assert error.value.code == "provider_unavailable"


async def test_reporting_service_retries_retryable_provider_failures() -> None:
    fixture_service = _build_service()
    fixture_dataset = await fixture_service.query_metric_series(
        MetricSeriesQuery(
            metric_names=["income"],
            dimension="reporting_period",
            granularity="month",
            limit=2,
        )
    )
    provider = FlakyReportingProvider(fixture_dataset)
    service = _build_service_with_provider(provider)

    result = await service.query_metric_series(
        MetricSeriesQuery(
            metric_names=["income"],
            dimension="reporting_period",
            granularity="month",
            limit=2,
        )
    )

    assert result.row_count == 2
    assert len(provider.calls) == 2


async def test_reporting_service_opens_circuit_after_repeated_retryable_failures() -> None:
    provider = AlwaysRetryableProvider()
    runtime = bootstrap()
    manifest = load_manifest(REPORTING_TOOL_DIR / "manifest.yaml")
    raw_config = load_tool_config(REPORTING_TOOL_DIR / "config.yaml")
    raw_config.update(
        {
            "retry_attempts": 1,
            "circuit_breaker_threshold": 2,
            "circuit_breaker_reset_seconds": 300,
        }
    )
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=raw_config,
    )
    service = ReportingService(
        context,
        config=load_reporting_tool_config(raw_config),
        provider=provider,
    )
    request = MetricSeriesQuery(
        metric_names=["income"],
        dimension="reporting_period",
        granularity="month",
        limit=1,
    )

    with pytest.raises(ReportingProviderError, match="unavailable"):
        await service.query_metric_series(request)
    with pytest.raises(ReportingProviderError, match="unavailable"):
        await service.query_metric_series(request)
    with pytest.raises(ReportingProviderError, match="temporarily unavailable"):
        await service.query_metric_series(request)

    health = service.health_payload()
    assert health["status"] == "error"
    assert health["circuit_breaker_state"] == "open"
    assert health["consecutive_provider_failures"] == 2


async def test_reporting_service_rejects_secret_like_filters_even_without_plugin_guard() -> None:
    service = _build_service()

    with pytest.raises(ReportingValidationError) as error:
        await service.query_metric_series(
            MetricSeriesQuery(
                metric_names=["income"],
                dimension="reporting_period",
                granularity="month",
                filters={"api_key": "abc123abcdefghijklmnop"},
                limit=1,
            )
        )

    assert error.value.code == "secret_argument"


async def test_reporting_service_limits_concurrency_to_configured_bound() -> None:
    fixture_service = _build_service()
    fixture_dataset = await fixture_service.query_metric_series(
        MetricSeriesQuery(
            metric_names=["income"],
            dimension="reporting_period",
            granularity="month",
            limit=1,
        )
    )
    provider = ConcurrencyTrackingProvider(fixture_dataset)
    runtime = bootstrap()
    manifest = load_manifest(REPORTING_TOOL_DIR / "manifest.yaml")
    raw_config = load_tool_config(REPORTING_TOOL_DIR / "config.yaml")
    raw_config["max_concurrency"] = 2
    raw_config["cache_ttl_seconds"] = 0
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=raw_config,
    )
    service = ReportingService(
        context,
        config=load_reporting_tool_config(raw_config),
        provider=provider,
    )

    await asyncio.gather(
        *[
            service.query_metric_series(
                MetricSeriesQuery(
                    metric_names=["income"],
                    dimension="reporting_period",
                    granularity="month",
                    limit=1,
                )
            )
            for _ in range(5)
        ]
    )

    assert provider.max_in_flight <= 2


async def test_reporting_service_rate_limit_key_is_actor_scoped() -> None:
    runtime = bootstrap()
    manifest = load_manifest(REPORTING_TOOL_DIR / "manifest.yaml")
    raw_config = load_tool_config(REPORTING_TOOL_DIR / "config.yaml")
    rate_limiter = RecordingRateLimiter()
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=raw_config,
        auth=StubAuthService(),
    )
    object.__setattr__(context, "rate_limiter", rate_limiter)
    service = ReportingService(
        context,
        config=load_reporting_tool_config(raw_config),
    )

    await service.query_metric_series(
        MetricSeriesQuery(
            metric_names=["income"],
            dimension="reporting_period",
            granularity="month",
            limit=1,
        )
    )

    assert len(rate_limiter.keys) == 1
    assert rate_limiter.keys[0].startswith(f"{RATE_LIMIT_KEY}:chart-agent:")
    assert "core" not in rate_limiter.keys[0]
    assert "USD" not in rate_limiter.keys[0]


async def test_reporting_service_aggregates_duplicate_buckets_and_warns_about_gaps() -> None:
    service = _build_service(config_overrides={"fixture_dataset": "truncated_result"})

    dataset = await service.query_metric_series(
        MetricSeriesQuery(
            metric_names=["income", "expense"],
            dimension="reporting_period",
            start_date="2026-01-01",
            end_date="2026-04-30",
            granularity="month",
            limit=2,
        )
    )

    assert dataset.rows == [
        {
            "reporting_period": "2026-01-01",
            "income": 17.0,
            "expense": 8.0,
        },
        {
            "reporting_period": "2026-03-01",
            "income": 100.0,
            "expense": 80.0,
        },
    ]
    assert dataset.row_count == 2
    assert dataset.total_row_count == 3
    assert dataset.truncated is True
    assert dataset.time_range is not None
    assert dataset.time_range.model_dump(mode="json") == {
        "start": "2026-01-01",
        "end": "2026-04-30",
    }
    assert dataset.warnings == [
        "Duplicate reporting_period values were aggregated before the result was returned.",
        "Time-series data is missing 1 month bucket(s) within the applied range.",
        "Result truncated to 2 rows to honor the effective row limit.",
    ]


async def test_reporting_service_returns_empty_result_warning_for_empty_fixture() -> None:
    service = _build_service(config_overrides={"fixture_dataset": "empty_result"})

    dataset = await service.query_metric_series(
        MetricSeriesQuery(
            metric_names=["income"],
            dimension="reporting_period",
            start_date="2026-07-01",
            end_date="2026-07-31",
            granularity="month",
            limit=10,
        )
    )

    assert dataset.rows == []
    assert dataset.row_count == 0
    assert dataset.total_row_count == 0
    assert dataset.truncated is False
    assert dataset.time_range is not None
    assert dataset.time_range.model_dump(mode="json") == {
        "start": "2026-07-01",
        "end": "2026-07-31",
    }
    assert dataset.warnings == ["No reporting data matched the approved query range."]


async def test_reporting_service_truncates_rows_to_fit_transport_limit() -> None:
    dataset = StructuredDatasetResponse(
        dataset_id="reporting.metric_series.transport_probe.v1",
        columns=[
            DatasetColumn(
                name="reporting_period",
                data_type="date",
                nullable=False,
                semantic_role="time",
            ),
            DatasetColumn(
                name="income",
                data_type="number",
                nullable=False,
                semantic_role="metric",
                unit="USD",
            ),
        ],
        rows=[
            {"reporting_period": f"2026-01-{day:02d}", "income": 125000.0 + day}
            for day in range(1, 7)
        ],
        row_count=6,
        total_row_count=6,
        truncated=False,
        source="reporting_fixture",
        query_summary="Transport probe.",
        warnings=[],
        provenance={"provider": "fixture", "fixture_dataset": "monthly_income_expense"},
    )
    provider = StubReportingProvider(dataset=dataset)
    runtime = bootstrap()
    manifest = load_manifest(REPORTING_TOOL_DIR / "manifest.yaml")
    raw_config = load_tool_config(REPORTING_TOOL_DIR / "config.yaml")
    raw_config["max_result_bytes"] = 1400
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=raw_config,
    )
    service = ReportingService(
        context,
        config=load_reporting_tool_config(raw_config),
        provider=provider,
    )

    result = await service.query_metric_series(
        MetricSeriesQuery(
            metric_names=["income"],
            dimension="reporting_period",
            granularity="month",
            limit=6,
        )
    )

    assert result.row_count < 6
    assert result.total_row_count == 6
    assert result.truncated is True
    assert any("transport size limit" in warning for warning in result.warnings)


async def test_reporting_service_emits_phase5_events_and_metrics_without_raw_filters() -> None:
    raw_config = load_tool_config(REPORTING_TOOL_DIR / "config.yaml")
    metrics = InMemoryMetricsRecorder()
    tracer = InMemoryTraceRecorder(redactor=Redactor())
    context = build_tool_context(
        tool_name="reporting",
        capability_name=CAPABILITY_NAME,
        tool_config=raw_config,
        metrics=metrics,
        tracer=tracer,
    )
    service = ReportingService(
        context,
        config=load_reporting_tool_config(raw_config),
    )
    request = MetricSeriesQuery(
        metric_names=["income"],
        dimension="reporting_period",
        filters={"business_unit": "core", "currency": "USD"},
        granularity="month",
        limit=2,
    )

    with trace_context_scope(
        build_trace_context(
            trace_id="trace-reporting-phase5-0001",
            request_id="request-reporting-phase5-0001",
            server_name=context.server_name,
            tool_name=RATE_LIMIT_KEY,
            capability_name=CAPABILITY_NAME,
        )
    ):
        first = await service.query_metric_series(request)
        second = await service.query_metric_series(request)

    assert first == second
    event_names = [event.event_name for event in tracer.events]
    assert MCP_REPORTING_QUERY_STARTED in event_names
    assert MCP_REPORTING_REQUEST_VALIDATED in event_names
    assert MCP_REPORTING_PROVIDER_CALL_STARTED in event_names
    assert MCP_REPORTING_PROVIDER_CALL_COMPLETED in event_names
    assert MCP_REPORTING_RESULT_NORMALIZED in event_names
    assert MCP_REPORTING_RESULT_TRUNCATED in event_names
    assert "mcp.reporting.provider.cache_hit" in event_names

    normalized_event = next(
        event for event in tracer.events if event.event_name == MCP_REPORTING_RESULT_NORMALIZED
    )
    assert normalized_event.payload["trace_id"] == "trace-reporting-phase5-0001"
    assert normalized_event.payload["request_id"] == "request-reporting-phase5-0001"
    assert normalized_event.payload["row_count"] == 2
    assert normalized_event.payload["total_row_count"] == 6

    assert metrics.counter_value(
        "mcp.reporting.query.call.count",
        {
            "tool_name": RATE_LIMIT_KEY,
            "capability_name": CAPABILITY_NAME,
            "status": "attempt",
        },
    ) == 2
    assert metrics.counter_value(
        "mcp.reporting.query.cache.miss.count",
        {
            "tool_name": RATE_LIMIT_KEY,
            "capability_name": CAPABILITY_NAME,
            "status": "ok",
        },
    ) == 1
    assert metrics.counter_value(
        "mcp.reporting.query.cache.hit.count",
        {
            "tool_name": RATE_LIMIT_KEY,
            "capability_name": CAPABILITY_NAME,
            "status": "ok",
        },
    ) == 1
    assert metrics.counter_value(
        "mcp.reporting.query.truncation.count",
        {
            "tool_name": RATE_LIMIT_KEY,
            "capability_name": CAPABILITY_NAME,
            "status": "ok",
        },
    ) == 2
    assert any(sample.name == "mcp.reporting.query.serialized_bytes" for sample in metrics.timing_samples)

    serialized_payloads = json.dumps([event.payload for event in tracer.events]).lower()
    assert '"filters"' not in serialized_payloads
    assert '"metric_names"' not in serialized_payloads
    assert "usd" not in serialized_payloads
