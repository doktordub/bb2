"""Tool discovery service for the configured MCP adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.config.view import MCPServerSettings
from app.tools.errors import MCPDiscoveryError
from app.tools.mcp.protocol_models import MCPClientAdapter, MCPToolDefinition
from app.tools.models import ToolDiscoverySnapshot
from app.tools.registry import ToolRegistry, ToolRegistryRefreshResult


@dataclass(frozen=True, slots=True)
class ToolDiscoveryService:
    """Discover tools from the configured MCP adapter and refresh the registry."""

    mcp_adapter: MCPClientAdapter
    server: MCPServerSettings

    async def discover(self) -> ToolDiscoverySnapshot:
        if not self.server.tool_discovery_enabled:
            return ToolDiscoverySnapshot(
                server_name=self.server.name,
                transport=self.server.transport,
                discovery_enabled=False,
                tools={},
                metadata={"reason": "tool_discovery_disabled"},
            )

        try:
            discovered = await self.mcp_adapter.list_tools()
        except Exception as exc:
            return ToolDiscoverySnapshot(
                server_name=self.server.name,
                transport=self.server.transport,
                discovery_enabled=True,
                discovered_at=_utc_now(),
                tools={},
                error=str(exc),
                metadata={"error_type": type(exc).__name__},
            )

        return _build_snapshot(self.server, discovered)

    async def refresh_registry(self, registry: ToolRegistry) -> ToolRegistryRefreshResult:
        snapshot = await self.discover()
        return registry.refresh_from_snapshot(snapshot)


def _build_snapshot(
    server: MCPServerSettings,
    discovered: list[MCPToolDefinition],
) -> ToolDiscoverySnapshot:
    tools: dict[str, MCPToolDefinition] = {}
    for tool in discovered:
        if tool.name in tools:
            raise MCPDiscoveryError(f"Duplicate MCP tool discovered: {tool.name}")
        tools[tool.name] = tool

    return ToolDiscoverySnapshot(
        server_name=server.name,
        transport=server.transport,
        discovery_enabled=True,
        discovered_at=_utc_now(),
        tools=tools,
        metadata={"discovered_tool_count": len(tools)},
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
