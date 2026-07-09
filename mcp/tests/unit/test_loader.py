from __future__ import annotations

from pathlib import Path
import textwrap

import yaml

from app.bootstrap import bootstrap


def _write_app_config(
    tmp_path: Path,
    *,
    tools_dir: Path,
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
                "tools": tools,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path


def _write_tool(
    tools_dir: Path,
    *,
    tool_name: str,
    local_label: str,
) -> None:
    tool_dir = tools_dir / tool_name
    tool_dir.mkdir(parents=True, exist_ok=True)
    (tool_dir / "plugin.py").write_text(
        textwrap.dedent(
            f"""
            from __future__ import annotations

            from dataclasses import dataclass, field
            from pathlib import Path

            from fastmcp import FastMCP

            from app.context import ToolRuntimeContext
            from app.tools_base.models import CapabilityDescriptor, ToolHealth
            from app.tools_base.plugin import ToolPlugin


            @dataclass(slots=True)
            class GeneratedPlugin:
                context: ToolRuntimeContext
                name: str = \"{tool_name}\"
                version: str = \"1.0.0\"
                capabilities: list[CapabilityDescriptor] = field(
                    default_factory=lambda: [
                        CapabilityDescriptor(
                            name=\"{tool_name}.echo\",
                            type=\"tool\",
                            description=\"Return the merged config label.\",
                            risk_level=\"read_only\",
                        )
                    ]
                )

                def register(self, mcp: FastMCP) -> None:
                    marker_file = Path(str(self.context.tool_config[\"marker_file\"]))
                    marker_file.parent.mkdir(parents=True, exist_ok=True)
                    with marker_file.open(\"a\", encoding=\"utf-8\") as handle:
                        handle.write(f\"{{self.name}}\\n\")

                    @mcp.tool(name=\"{tool_name}.echo\")
                    def echo() -> dict[str, object]:
                        return {{
                            \"ok\": True,
                            \"tool_name\": \"{tool_name}.echo\",
                            \"data\": {{
                                \"label\": str(self.context.tool_config[\"label\"]),
                                \"timeout_seconds\": int(self.context.tool_config[\"timeout_seconds\"]),
                            }},
                        }}

                async def health(self) -> ToolHealth:
                    return ToolHealth(state=\"ok\")


            def create_plugin(context: ToolRuntimeContext) -> ToolPlugin:
                return GeneratedPlugin(context)
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (tool_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "name": tool_name,
                "package": f"mcp.tools.{tool_name}",
                "version": "1.0.0",
                "status": "experimental",
                "owner": "tests",
                "required": True,
                "description": "Generated loader fixture.",
                "capabilities": [
                    {
                        "name": f"{tool_name}.echo",
                        "type": "tool",
                        "description": "Return the merged config label.",
                        "risk_level": "read_only",
                    }
                ],
                "tools": [
                    {
                        "name": f"{tool_name}.echo",
                        "function": "echo",
                        "capability": f"{tool_name}.echo",
                        "description": "Return the merged config label.",
                        "risk_level": "read_only",
                        "input_schema": {"type": "object", "properties": {}},
                        "tags": ["generated", "loader"],
                    }
                ],
                "config_schema": {
                    "type": "object",
                    "required": ["label", "marker_file"],
                    "properties": {
                        "label": {"type": "string", "minLength": 1},
                        "marker_file": {"type": "string", "minLength": 1},
                    },
                    "additionalProperties": False,
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (tool_dir / "config.yaml").write_text(
        yaml.safe_dump({"label": local_label}, sort_keys=False),
        encoding="utf-8",
    )


async def test_loader_discovers_enabled_tools_in_deterministic_order_and_merges_config(
    tmp_path: Path,
) -> None:
    tools_dir = tmp_path / "tools"
    marker_file = tmp_path / "load-order.txt"
    _write_tool(tools_dir, tool_name="beta_tool", local_label="beta-local")
    _write_tool(tools_dir, tool_name="alpha_tool", local_label="alpha-local")
    config_path = _write_app_config(
        tmp_path,
        tools_dir=tools_dir,
        tools={
            "beta_tool": {
                "enabled": True,
                "required": True,
                "marker_file": marker_file.as_posix(),
                "label": "beta-global",
            },
            "alpha_tool": {
                "enabled": True,
                "required": True,
                "marker_file": marker_file.as_posix(),
                "label": "alpha-global",
            },
        },
    )

    runtime = bootstrap(config_path)
    alpha_result = await runtime.server.call_tool("alpha_tool.echo", {})
    beta_result = await runtime.server.call_tool("beta_tool.echo", {})

    assert marker_file.read_text(encoding="utf-8").splitlines() == ["alpha_tool", "beta_tool"]
    assert alpha_result.structured_content == {
        "ok": True,
        "tool_name": "alpha_tool.echo",
        "data": {
            "label": "alpha-local",
            "timeout_seconds": 30,
        },
    }
    assert beta_result.structured_content == {
        "ok": True,
        "tool_name": "beta_tool.echo",
        "data": {
            "label": "beta-local",
            "timeout_seconds": 30,
        },
    }


async def test_default_app_config_loads_required_websearch_plugin() -> None:
    runtime = bootstrap()
    registered_tool = runtime.registry.get_tool("websearch")
    tools = await runtime.server.list_tools()

    assert registered_tool is not None
    assert registered_tool.load_status == "loaded"
    assert registered_tool.required is True
    assert registered_tool.fastmcp_tool_names == ("websearch.search",)
    assert any(tool.name == "websearch.search" for tool in tools)
