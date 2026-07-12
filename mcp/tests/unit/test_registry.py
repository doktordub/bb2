from pathlib import Path

import pytest

from app.errors import MCPToolPluginError
from app.registry import ToolRegistry
from app.tools_base.manifest import ToolManifest
from app.tools_base.models import CapabilityDescriptor, ToolHealth
from app.tools_base.validation import load_manifest, load_tool_config, validate_plugin_instance
from tools.example_tool.plugin import create_plugin
from app.bootstrap import bootstrap
from fastmcp import FastMCP


EXAMPLE_TOOL_DIR = Path(__file__).resolve().parents[2] / "tools" / "example_tool"


class DuplicatePlugin:
    def __init__(self, *, name: str, version: str, capabilities: list[CapabilityDescriptor]) -> None:
        self.name = name
        self.version = version
        self.capabilities = capabilities

    def register(self, mcp: FastMCP) -> None:
        del mcp

    async def health(self) -> ToolHealth:
        return ToolHealth(state="ok")


def test_registry_records_loaded_tool_and_capabilities() -> None:
    runtime = bootstrap()
    manifest = load_manifest(EXAMPLE_TOOL_DIR / "manifest.yaml")
    config = load_tool_config(EXAMPLE_TOOL_DIR / "config.yaml")
    plugin = create_plugin(
        runtime.services.build_tool_runtime_context(
            tool_name=manifest.name,
            tool_config=config,
        )
    )
    validate_plugin_instance(plugin, manifest)

    registry = ToolRegistry()
    registry.register_plugin(plugin, manifest, config)

    registered_tool = registry.get_tool("example_tool")

    assert registered_tool is not None
    assert registered_tool.load_status == "loaded"
    assert registered_tool.fastmcp_tool_names == ("example.echo",)
    assert [capability.to_summary() for capability in registry.list_capabilities()] == [
        {
            "capability_name": "example.echo",
            "type": "tool",
            "tool_name": "example.echo",
            "risk_level": "read_only",
            "enabled": True,
            "status": "loaded",
            "health": "ok",
            "version": "1.0.0",
            "owner": "platform",
            "tags": ["echo", "example", "read_only"],
            "input_schema": {
                "type": "object",
                "required": ["message"],
                "properties": {
                    "message": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                    },
                    "uppercase": {"type": "boolean"},
                },
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "tool_name": {"type": "string"},
                    "summary": {"type": "object"},
                    "data": {"type": "object"},
                },
            },
            "schema_version": None,
        }
    ]
    assert registry.health_summary().as_counts() == {
        "loaded": 1,
        "enabled": 1,
        "disabled": 0,
        "failed": 0,
        "unhealthy": 0,
    }


def test_registry_detects_duplicate_fastmcp_tool_names() -> None:
    runtime = bootstrap()
    manifest = load_manifest(EXAMPLE_TOOL_DIR / "manifest.yaml")
    config = load_tool_config(EXAMPLE_TOOL_DIR / "config.yaml")
    plugin = create_plugin(
        runtime.services.build_tool_runtime_context(
            tool_name=manifest.name,
            tool_config=config,
        )
    )
    validate_plugin_instance(plugin, manifest)

    registry = ToolRegistry()
    registry.register_plugin(plugin, manifest, config)

    duplicate_manifest = ToolManifest.model_validate(
        {
            **manifest.model_dump(mode="python"),
            "name": "duplicate_tool",
            "package": "mcp.tools.duplicate_tool",
        }
    )
    duplicate_plugin = DuplicatePlugin(
        name=duplicate_manifest.name,
        version=duplicate_manifest.version,
        capabilities=duplicate_manifest.capability_descriptors(),
    )

    with pytest.raises(MCPToolPluginError, match="Duplicate FastMCP tool name"):
        registry.register_plugin(duplicate_plugin, duplicate_manifest, config)