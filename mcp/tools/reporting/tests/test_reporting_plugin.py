from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP

from app.bootstrap import bootstrap
from app.tools_base.dataset_models import DatasetColumn, StructuredDatasetResponse
from app.tools_base.validation import load_manifest, load_tool_config, validate_plugin_instance
from tools.reporting.providers import ReportingProviderError
from tools.reporting.plugin import ReportingPlugin, create_plugin


REPORTING_TOOL_DIR = Path(__file__).resolve().parents[1]


def _build_context(*, config_overrides: dict[str, object] | None = None):
    runtime = bootstrap()
    manifest = load_manifest(REPORTING_TOOL_DIR / "manifest.yaml")
    tool_config = load_tool_config(REPORTING_TOOL_DIR / "config.yaml")
    if config_overrides:
        tool_config.update(config_overrides)
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=tool_config,
    )
    return manifest, context


class StubReportingService:
    def __init__(self) -> None:
        self.metric_names: list[list[str]] = []

    async def query_metric_series(self, request) -> StructuredDatasetResponse:
        self.metric_names.append(list(request.metric_names))
        return StructuredDatasetResponse(
            dataset_id="reporting.metric_series.stub.v1",
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
            rows=[{"reporting_period": "2026-01-01", "income": 125000.0}],
            row_count=1,
            total_row_count=1,
            truncated=False,
            source="reporting_fixture",
            query_summary="Returned one fixture row.",
            warnings=[],
            provenance={"provider": "fixture"},
        )

    def health_payload(self) -> dict[str, object]:
        return {
            "status": "ok",
            "provider": "fixture",
            "provider_check": "skipped",
            "configured_metrics": 2,
        }


class FailingReportingService:
    async def query_metric_series(self, request) -> StructuredDatasetResponse:
        del request
        raise ReportingProviderError(
            "provider_unavailable",
            "Reporting provider is unavailable.",
            summary="The reporting provider is unavailable right now.",
            retryable=True,
        )

    def health_payload(self) -> dict[str, object]:
        return {
            "status": "ok",
            "provider": "fixture",
            "provider_check": "skipped",
            "configured_metrics": 2,
        }


async def test_reporting_plugin_registers_and_executes() -> None:
    manifest, context = _build_context()

    service = StubReportingService()
    plugin = ReportingPlugin(context, service=service)
    validate_plugin_instance(plugin, manifest)

    server = FastMCP("reporting-contract-test")
    plugin.register(server)
    tools = await server.list_tools()
    result = await server.call_tool(
        "reporting.query_metric_series",
        {
            "metric_names": ["income"],
            "dimension": "reporting_period",
            "granularity": "month",
            "limit": 1,
        },
    )

    assert any(tool.name == "reporting.query_metric_series" for tool in tools)
    assert service.metric_names == [["income"]]
    assert result.structured_content == {
        "ok": True,
        "tool_name": "reporting.query_metric_series",
        "summary": {
            "message": "Returned one fixture row.",
            "item_count": 1,
            "truncated": False,
        },
        "data": {
            "dataset": {
                "schema_version": "1.0",
                "dataset_id": "reporting.metric_series.stub.v1",
                "columns": [
                    {
                        "name": "reporting_period",
                        "data_type": "date",
                        "nullable": False,
                        "semantic_role": "time",
                        "unit": None,
                    },
                    {
                        "name": "income",
                        "data_type": "number",
                        "nullable": False,
                        "semantic_role": "metric",
                        "unit": "USD",
                    },
                ],
                "rows": [{"reporting_period": "2026-01-01", "income": 125000.0}],
                "row_count": 1,
                "total_row_count": 1,
                "truncated": False,
                "source": "reporting_fixture",
                "query_summary": "Returned one fixture row.",
                "time_range": None,
                "warnings": [],
                "provenance": {"provider": "fixture"},
            }
        },
        "errors": [],
        "meta": {
            "schema_version": "1.0",
            "output_schema": "structured_dataset_v1",
            "dataset_id": "reporting.metric_series.stub.v1",
        },
    }


async def test_reporting_plugin_health_is_safe_and_bounded() -> None:
    _, context = _build_context()

    plugin = create_plugin(context)
    health = await plugin.health()

    assert health.state == "ok"
    assert health.details["status"] == "ok"
    assert health.details["plugin_loaded"] is True
    assert health.details["tool_name"] == "reporting.query_metric_series"
    assert health.details["capability_name"] == "reporting.metric_series.read"
    assert health.details["provider"] == "fixture"
    assert health.details["provider_configured"] is True
    assert health.details["provider_health_status"] == "ok"
    assert health.details["fixture_dataset"] == "monthly_income_expense"
    assert health.details["healthcheck_mode"] == "safe"
    assert health.details["provider_check"] == "skipped"
    assert health.details["configured_metrics"] == 2
    assert health.details["configured_dimensions"] == 1
    assert health.details["auth_profile_configured"] is False
    assert health.details["max_concurrency"] == 4
    assert health.details["retry_attempts"] == 2
    assert health.details["circuit_breaker_threshold"] == 3
    assert health.details["circuit_breaker_state"] == "closed"
    assert health.details["consecutive_provider_failures"] == 0
    assert isinstance(health.details["last_check_at"], str)
    assert "token" not in str(health.details).lower()


async def test_reporting_plugin_returns_structured_provider_errors() -> None:
    _, context = _build_context()

    plugin = ReportingPlugin(context, service=FailingReportingService())
    server = FastMCP("reporting-error-test")
    plugin.register(server)

    result = await server.call_tool(
        "reporting.query_metric_series",
        {
            "metric_names": ["income"],
            "dimension": "reporting_period",
            "granularity": "month",
            "limit": 1,
        },
    )

    assert result.structured_content == {
        "ok": False,
        "tool_name": "reporting.query_metric_series",
        "summary": {
            "message": "The reporting provider is unavailable right now.",
            "item_count": 0,
            "truncated": False,
        },
        "data": {},
        "errors": [
            {
                "code": "provider_unavailable",
                "message": "Reporting provider is unavailable.",
                "retryable": True,
                "details": {},
            }
        ],
        "meta": {
            "schema_version": "1.0",
            "output_schema": "structured_dataset_v1",
        },
    }


async def test_reporting_plugin_enforces_configured_result_byte_limit() -> None:
    _, context = _build_context(config_overrides={"max_result_bytes": 256})

    plugin = ReportingPlugin(context, service=StubReportingService())
    server = FastMCP("reporting-byte-limit-test")
    plugin.register(server)

    result = await server.call_tool(
        "reporting.query_metric_series",
        {
            "metric_names": ["income"],
            "dimension": "reporting_period",
            "granularity": "month",
            "limit": 1,
        },
    )

    assert result.structured_content["ok"] is False
    assert result.structured_content["errors"] == [
        {
            "code": "result_too_large",
            "message": "Reporting provider returned more data than this tool is allowed to send.",
            "retryable": False,
            "details": {},
        }
    ]
