from __future__ import annotations

from app.testing.fakes import FakeConfigurationView
from app.tools.factory import build_tooling_runtime
from app.tools.mcp import DefaultMCPClientAdapter, FakeMCPClientAdapter, MCPToolDefinition


def build_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "tooling": {
                "enabled": True,
                "defaults": {
                    "timeout_seconds": 45,
                    "stream_timeout_seconds": 90,
                    "max_retries": 2,
                    "max_argument_bytes": 4096,
                    "max_result_bytes": 65536,
                    "trace_arguments": False,
                    "trace_results": False,
                    "discovery_on_startup": True,
                    "discovery_refresh_seconds": 120,
                },
                "registry": {
                    "allow_discovered_tools": True,
                    "require_configured_allowlist": True,
                    "tools": {
                        "documents.search": {
                            "enabled": True,
                            "mcp_tool_name": "documents.search",
                            "description": "Search indexed documents.",
                            "allowed_for": {
                                "usecases": ["default_chat"],
                                "agents": ["support_agent"],
                                "strategies": ["direct_agent"],
                            },
                            "timeout_seconds": 30,
                            "max_argument_bytes": 2048,
                            "max_result_bytes": 16384,
                            "approval_required": False,
                            "input_schema_override": {"type": "object"},
                            "output_schema_override": {"type": "object"},
                            "tags": ["documents", "search"],
                            "safety_level": "read_only",
                            "extra": {"supports_streaming": True},
                        },
                        "admin.reset_cache": {
                            "enabled": False,
                            "mcp_tool_name": "admin.reset_cache",
                            "description": "Reset remote caches.",
                            "allowed_for": {
                                "usecases": ["default_chat"],
                                "agents": [],
                                "strategies": [],
                            },
                            "approval_required": True,
                            "tags": ["admin"],
                            "safety_level": "destructive",
                            "extra": {},
                        },
                    },
                },
            },
            "mcp": {
                "main": {
                    "name": "fake_main",
                    "enabled": True,
                    "endpoint": "http://localhost:9001/mcp",
                    "transport": "sse",
                    "timeout_seconds": 45,
                    "stream_timeout_seconds": 90,
                    "auth": {"mode": "none"},
                    "tool_discovery_enabled": True,
                }
            },
        }
    )


def test_build_tooling_runtime_creates_real_adapter_bundle_from_config() -> None:
    runtime = build_tooling_runtime(build_config())

    assert isinstance(runtime.mcp_adapter, DefaultMCPClientAdapter)
    assert tuple(runtime.registry_entries) == ("documents.search", "admin.reset_cache")
    assert runtime.registry_entries["documents.search"].definition.supports_streaming is True
    assert runtime.registry_entries["admin.reset_cache"].definition.enabled is False
    assert runtime.discovery_snapshot.server_name == "fake_main"
    assert runtime.discovery_snapshot.tool_names == ("documents.search",)


def test_build_tooling_runtime_preserves_explicit_adapter_override() -> None:
    adapter = FakeMCPClientAdapter(
        discovered_tools=[MCPToolDefinition(name="override.tool")],
        endpoint="http://override/mcp",
    )

    runtime = build_tooling_runtime(build_config(), mcp_adapter=adapter)

    assert runtime.mcp_adapter is adapter
    assert runtime.discovery_snapshot.tool_count == 1