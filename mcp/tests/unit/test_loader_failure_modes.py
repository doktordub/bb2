from __future__ import annotations

from pathlib import Path
import shutil

import pytest
import yaml

from app.bootstrap import bootstrap
from app.errors import MCPToolManifestError, MCPToolPluginError


FIXTURE_TOOLS_DIR = Path(__file__).resolve().parent / "fixtures" / "tools"


def _copy_fixture_tools(tmp_path: Path, *tool_names: str) -> Path:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    for tool_name in tool_names:
        shutil.copytree(FIXTURE_TOOLS_DIR / tool_name, tools_dir / tool_name)
    return tools_dir


def _write_app_config(
    tmp_path: Path,
    *,
    tools_dir: Path,
    tools: dict[str, dict[str, object]],
    fail_on_optional_tool_error: bool = False,
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
                    "tools_dir": tools_dir.as_posix(),
                    "discovery_on_startup": True,
                    "fail_on_required_tool_error": True,
                    "fail_on_optional_tool_error": fail_on_optional_tool_error,
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


async def test_optional_failing_plugin_degrades_and_is_not_registered(tmp_path: Path) -> None:
    tools_dir = _copy_fixture_tools(tmp_path, "failing_plugin")
    runtime = bootstrap(
        _write_app_config(
            tmp_path,
            tools_dir=tools_dir,
            tools={"failing_plugin": {"enabled": True, "required": False}},
        )
    )
    tools = await runtime.server.list_tools()
    registered_tool = runtime.registry.get_tool("failing_plugin")

    assert registered_tool is not None
    assert registered_tool.load_status == "failed"
    assert registered_tool.health_status == "error"
    assert registered_tool.last_load_error is not None
    assert registered_tool.last_load_error.message == "plugin startup failed"
    assert all(tool.name != "failing.echo" for tool in tools)


def test_required_failing_plugin_fails_startup(tmp_path: Path) -> None:
    tools_dir = _copy_fixture_tools(tmp_path, "failing_plugin")

    with pytest.raises(RuntimeError, match="plugin startup failed"):
        bootstrap(
            _write_app_config(
                tmp_path,
                tools_dir=tools_dir,
                tools={"failing_plugin": {"enabled": True, "required": True}},
            )
        )


def test_duplicate_fastmcp_tool_names_fail_startup(tmp_path: Path) -> None:
    tools_dir = _copy_fixture_tools(tmp_path, "duplicate_tool_a", "duplicate_tool_b")

    with pytest.raises(MCPToolPluginError, match="Duplicate FastMCP tool name"):
        bootstrap(
            _write_app_config(
                tmp_path,
                tools_dir=tools_dir,
                tools={
                    "duplicate_tool_a": {"enabled": True, "required": True},
                    "duplicate_tool_b": {"enabled": True, "required": True},
                },
            )
        )


async def test_disabled_tools_are_not_imported_or_registered_with_fastmcp(tmp_path: Path) -> None:
    tools_dir = _copy_fixture_tools(tmp_path, "disabled_tool")
    runtime = bootstrap(
        _write_app_config(
            tmp_path,
            tools_dir=tools_dir,
            tools={"disabled_tool": {"enabled": False, "required": False}},
        )
    )
    tools = await runtime.server.list_tools()
    registered_tool = runtime.registry.get_tool("disabled_tool")

    assert registered_tool is not None
    assert registered_tool.load_status == "disabled"
    assert all(tool.name != "disabled.echo" for tool in tools)


def test_invalid_manifest_fails_enabled_tool_startup(tmp_path: Path) -> None:
    tools_dir = _copy_fixture_tools(tmp_path, "invalid_manifest")

    with pytest.raises(MCPToolManifestError, match="must match folder name"):
        bootstrap(
            _write_app_config(
                tmp_path,
                tools_dir=tools_dir,
                tools={"invalid_manifest": {"enabled": True, "required": True}},
            )
        )