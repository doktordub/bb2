from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.bootstrap import bootstrap
from app.errors import MCPToolConfigurationError


MCP_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = MCP_ROOT / "tools"


def _write_app_config(
    tmp_path: Path,
    *,
    tools: dict[str, dict[str, object]],
) -> Path:
    config_path = tmp_path / "app.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "server": {
                    "name": "main_mcp",
                    "version": "1.0.0",
                    "environment": "test",
                    "host": "127.0.0.1",
                    "port": 9001,
                    "path": "/mcp",
                    "transport": "http",
                },
                "runtime": {
                    "tools_dir": TOOLS_DIR.as_posix(),
                    "discovery_on_startup": True,
                    "fail_on_required_tool_error": True,
                    "fail_on_optional_tool_error": False,
                },
                "security": {
                    "inbound_auth": {"enabled": False, "mode": "none"},
                    "outbound_auth": {"default_mode": "none"},
                    "tls": {"mode": "terminate_upstream", "behind_proxy": True},
                    "secrets": {
                        "provider": "env",
                        "allow_tool_env_prefixes": ["MCP_TOOL_", "WEBSEARCH_"],
                    },
                },
                "policy": {
                    "default_tool_enabled": False,
                    "expose_internal_tools": True,
                    "expose_health_tool": True,
                    "expose_capabilities_tool": True,
                    "require_tool_manifest": True,
                    "require_tool_config_validation": True,
                    "reject_secret_like_arguments": True,
                },
                "observability": {
                    "log_level": "INFO",
                    "json_logs": True,
                    "trace_headers": {},
                    "redact_secrets": True,
                    "metrics_enabled": False,
                    "max_log_payload_chars": 2000,
                },
                "defaults": {
                    "timeout_seconds": 30,
                    "max_result_bytes": 262144,
                    "max_argument_bytes": 65536,
                    "max_results": 10,
                    "rate_limit": {
                        "enabled": True,
                        "per_tool_per_minute": 60,
                    },
                },
                "tools": tools,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path


async def test_reporting_loader_registers_tool_and_capability(tmp_path: Path) -> None:
    runtime = bootstrap(
        _write_app_config(
            tmp_path,
            tools={
                "reporting": {
                    "enabled": True,
                    "required": False,
                    "config_file": "config.yaml",
                }
            },
        )
    )
    tools = await runtime.server.list_tools()
    registered_tool = runtime.registry.get_tool("reporting")
    capability_result = await runtime.server.call_tool("mcp.capabilities", {})

    assert registered_tool is not None
    assert registered_tool.load_status == "loaded"
    assert registered_tool.fastmcp_tool_names == ("reporting.query_metric_series",)
    assert registered_tool.health_status == "ok"
    assert registered_tool.health_details["provider_health_status"] == "ok"
    assert any(tool.name == "reporting.query_metric_series" for tool in tools)
    assert any(
        item["tool_name"] == "reporting.query_metric_series"
        for item in capability_result.structured_content["capabilities"]
    )
    capability_entry = next(
        item
        for item in capability_result.structured_content["capabilities"]
        if item["tool_name"] == "reporting.query_metric_series"
    )
    assert capability_entry["health"] == "ok"
    assert capability_entry["owner"] == "platform"
    assert capability_entry["tags"] == [
        "metrics",
        "read_only",
        "reporting",
        "visualization_ready",
    ]
    assert capability_entry["input_schema"] == "auto"
    assert capability_entry["output_schema"] == "structured_dataset_v1"
    assert capability_entry["schema_version"] == "1.0"


async def test_reporting_loader_skips_disabled_plugin(tmp_path: Path) -> None:
    runtime = bootstrap(
        _write_app_config(
            tmp_path,
            tools={"reporting": {"enabled": False, "required": False}},
        )
    )
    tools = await runtime.server.list_tools()
    registered_tool = runtime.registry.get_tool("reporting")

    assert registered_tool is not None
    assert registered_tool.load_status == "disabled"
    assert all(tool.name != "reporting.query_metric_series" for tool in tools)


def test_reporting_loader_invalid_config_fails_clearly(tmp_path: Path) -> None:
    invalid_config_path = tmp_path / "reporting-invalid.yaml"
    invalid_config_path.write_text(
        yaml.safe_dump(
            {
                "provider": "fixture",
                "fixture_dataset": "monthly_income_expense",
                "enabled_metrics": ["income", "expense"],
                "enabled_dimensions": ["reporting_period"],
                "max_date_range_days": 730,
                "default_granularity": "month",
                "maximum_rows": 0,
                "maximum_metrics_per_query": 3,
                "maximum_filters": 5,
                "timeout_seconds": 20,
                "cache_ttl_seconds": 60,
                "provider_auth_profile": "none",
                "healthcheck_mode": "safe",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(MCPToolConfigurationError, match="maximum_rows"):
        bootstrap(
            _write_app_config(
                tmp_path,
                tools={
                    "reporting": {
                        "enabled": True,
                        "required": True,
                        "config_file": invalid_config_path.as_posix(),
                    }
                },
            )
        )
