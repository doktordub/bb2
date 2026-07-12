from pathlib import Path

from app.bootstrap import bootstrap
from app.errors import MCPToolConfigurationError
from app.tools_base.dataset_models import MetricSeriesQuery
from app.tools_base.validation import load_manifest, load_tool_config

from tools.reporting.models import load_reporting_tool_config
from tools.reporting.providers import FixtureReportingProvider, ReportingProviderError


REPORTING_TOOL_DIR = Path(__file__).resolve().parents[1]


def _build_provider(*, config_overrides: dict[str, object] | None = None) -> FixtureReportingProvider:
    runtime = bootstrap()
    manifest = load_manifest(REPORTING_TOOL_DIR / "manifest.yaml")
    raw_config = load_tool_config(REPORTING_TOOL_DIR / "config.yaml")
    if config_overrides:
        raw_config.update(config_overrides)
    context = runtime.services.build_tool_runtime_context(
        tool_name=manifest.name,
        tool_config=raw_config,
    )

    return FixtureReportingProvider(
        context=context,
        config=load_reporting_tool_config(raw_config),
    )


async def test_fixture_reporting_provider_translates_fixture_fields_into_dataset_rows() -> None:
    provider = _build_provider()

    dataset = await provider.query_metric_series(
        MetricSeriesQuery(
            metric_names=["income", "expense"],
            dimension="reporting_period",
            start_date="2026-01-01",
            end_date="2026-02-28",
            filters={"business_unit": "core", "currency": "USD"},
            aggregation="sum",
            granularity="month",
            limit=10,
        ),
        trusted_scope={"business_unit": "core", "currency": "USD"},
    )

    assert dataset.row_count == 2
    assert dataset.rows == [
        {
            "reporting_period": "2026-01-01",
            "income": 125000.0,
            "expense": 101000.0,
        },
        {
            "reporting_period": "2026-02-01",
            "income": 131500.0,
            "expense": 104250.0,
        },
    ]
    assert dataset.provenance["fixture_dataset"] == "monthly_income_expense"


async def test_fixture_reporting_provider_rejects_scope_mismatch() -> None:
    provider = _build_provider()

    try:
        await provider.query_metric_series(
            MetricSeriesQuery(
                metric_names=["income"],
                dimension="reporting_period",
                granularity="month",
                filters={"business_unit": "other", "currency": "USD"},
                limit=1,
            ),
            trusted_scope={"business_unit": "core", "currency": "USD"},
        )
    except ReportingProviderError as error:
        assert error.code == "unauthorized_scope"
    else:  # pragma: no cover - defensive failure branch
        raise AssertionError("Expected provider scope validation to fail.")


def test_fixture_reporting_provider_rejects_invalid_numeric_rows_at_load_time() -> None:
    try:
        _build_provider(config_overrides={"fixture_dataset": "invalid_numeric_result"})
    except MCPToolConfigurationError as error:
        assert "invalid_numeric_result" in str(error)
    else:  # pragma: no cover - defensive failure branch
        raise AssertionError("Expected invalid fixture rows to fail provider initialization.")