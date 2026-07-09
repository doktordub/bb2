from __future__ import annotations

import json
from pathlib import Path
import shutil

import yaml

from app.bootstrap import bootstrap


FIXTURE_TOOLS_DIR = Path(__file__).resolve().parent / "fixtures" / "tools"


def _copy_fixture_tool(tmp_path: Path, tool_name: str) -> Path:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE_TOOLS_DIR / tool_name, tools_dir / tool_name)
    return tools_dir


def _write_app_config(tmp_path: Path, *, tools_dir: Path) -> Path:
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
                "tools": {
                    "valid_tool": {
                        "enabled": True,
                        "required": True,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path


async def test_capability_and_tool_summaries_are_safe_and_accurate(tmp_path: Path) -> None:
    tools_dir = _copy_fixture_tool(tmp_path, "valid_tool")
    runtime = bootstrap(_write_app_config(tmp_path, tools_dir=tools_dir))

    capability_result = await runtime.server.call_tool("mcp.capabilities", {})
    tools_result = await runtime.server.call_tool("mcp.tools.list", {})
    health_result = await runtime.server.call_tool("mcp.health", {})
    registry_serialized = json.dumps(
        {
            "capabilities": capability_result.structured_content,
            "tools": tools_result.structured_content,
        }
    )

    assert capability_result.structured_content == {
        "server": "main_mcp",
        "capabilities": [
            {
                "capability_name": "valid.echo",
                "type": "tool",
                "tool_name": "valid.echo",
                "risk_level": "read_only",
                "enabled": True,
                "status": "loaded",
                "version": "1.0.0",
            }
        ],
    }
    assert tools_result.structured_content == {
        "server": "main_mcp",
        "tools": [
            {
                "name": "valid_tool",
                "version": "1.0.0",
                "enabled": True,
                "required": True,
                "status": "loaded",
                "health": "ok",
                "tools": ["valid.echo"],
                "owner": "tests",
                "tags": ["fixture", "valid"],
                "last_error": None,
            }
        ],
    }
    assert health_result.structured_content["tools"] == {
        "loaded": 1,
        "enabled": 1,
        "disabled": 0,
        "failed": 0,
        "unhealthy": 0,
    }
    assert "valid-local" not in registry_serialized
    assert "config_file" not in registry_serialized
