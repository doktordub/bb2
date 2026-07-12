from app.errors import MCPToolConfigurationError
import pytest

from tools.reporting.models import load_reporting_tool_config


def test_reporting_tool_config_normalizes_lists_and_auth_profile() -> None:
    config = load_reporting_tool_config(
        {
            "provider": "fixture",
            "fixture_dataset": "monthly_income_expense",
            "enabled_metrics": [" income ", "expense"],
            "enabled_dimensions": [" reporting_period "],
            "max_date_range_days": 365,
            "default_granularity": "month",
            "maximum_rows": 24,
            "maximum_metrics_per_query": 3,
            "maximum_filters": 5,
            "timeout_seconds": 20,
            "cache_ttl_seconds": 60,
            "provider_auth_profile": " none ",
            "healthcheck_mode": "safe",
        }
    )

    assert config.enabled_metrics == ["income", "expense"]
    assert config.enabled_dimensions == ["reporting_period"]
    assert config.provider_auth_profile == "none"
    assert config.auth_profile_configured is False


def test_reporting_tool_config_rejects_fixture_auth_profile_override() -> None:
    with pytest.raises(MCPToolConfigurationError, match="provider_auth_profile"):
        load_reporting_tool_config(
            {
                "provider": "fixture",
                "fixture_dataset": "monthly_income_expense",
                "enabled_metrics": ["income", "expense"],
                "enabled_dimensions": ["reporting_period"],
                "max_date_range_days": 365,
                "default_granularity": "month",
                "maximum_rows": 24,
                "maximum_metrics_per_query": 3,
                "maximum_filters": 5,
                "provider_auth_profile": "reporting_readonly",
                "healthcheck_mode": "safe",
            }
        )


def test_reporting_tool_config_rejects_duplicate_metric_names() -> None:
    try:
        load_reporting_tool_config(
            {
                "provider": "fixture",
                "fixture_dataset": "monthly_income_expense",
                "enabled_metrics": ["income", "Income"],
                "enabled_dimensions": ["reporting_period"],
                "max_date_range_days": 365,
                "default_granularity": "month",
                "maximum_rows": 24,
                "maximum_metrics_per_query": 3,
                "maximum_filters": 5,
                "timeout_seconds": 20,
                "cache_ttl_seconds": 60,
                "provider_auth_profile": "none",
                "healthcheck_mode": "safe",
            }
        )
    except MCPToolConfigurationError as error:
        assert "duplicate identifier" in str(error)
    else:  # pragma: no cover - defensive failure branch
        raise AssertionError("Expected duplicate enabled_metrics to fail validation.")
