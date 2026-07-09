"""Safe capability and tool summary endpoints for the MCP server."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from app.context import ToolRuntimeContext
from app.registry import ToolRegistry
from app.tools_base.decorators import observe_tool_call


def build_capabilities_payload(server_name: str, registry: ToolRegistry) -> dict[str, Any]:
    return {
        "server": server_name,
        "capabilities": [capability.to_summary() for capability in registry.list_capabilities()],
    }


def build_tools_payload(server_name: str, registry: ToolRegistry) -> dict[str, Any]:
    return {
        "server": server_name,
        "tools": [tool.to_summary() for tool in registry.list_tools()],
    }


def register_capability_tools(
    server: FastMCP,
    context: ToolRuntimeContext,
    registry: ToolRegistry,
) -> None:
    @server.tool(name="mcp.capabilities")
    @observe_tool_call(context, "mcp.capabilities", capability_name="mcp.capabilities")
    def capabilities() -> dict[str, Any]:
        return build_capabilities_payload(context.server_name, registry)

    @server.tool(name="mcp.tools.list")
    @observe_tool_call(context, "mcp.tools.list", capability_name="mcp.tools.list")
    def tools_list() -> dict[str, Any]:
        return build_tools_payload(context.server_name, registry)
