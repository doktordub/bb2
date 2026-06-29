from __future__ import annotations

import pytest

from app.config.view import MCPAuthSettings, MCPServerSettings
from app.tools.discovery import ToolDiscoveryService
from app.tools.mcp import FakeMCPClientAdapter, MCPToolDefinition


def build_server_settings() -> MCPServerSettings:
    return MCPServerSettings(
        name="fake_main",
        enabled=True,
        endpoint="http://localhost:9001/mcp",
        transport="http",
        timeout_seconds=45,
        stream_timeout_seconds=90,
        auth=MCPAuthSettings(
            mode="none",
            token=None,
            jwt=None,
            token_url=None,
            client_id=None,
            client_secret=None,
            scopes=(),
        ),
        tool_discovery_enabled=True,
    )


@pytest.mark.asyncio
async def test_discovery_service_reads_tools_from_adapter() -> None:
    adapter = FakeMCPClientAdapter(
        discovered_tools=[
            MCPToolDefinition(name="documents.search"),
            MCPToolDefinition(name="filesystem.read_project_file", supports_streaming=True),
        ]
    )
    service = ToolDiscoveryService(mcp_adapter=adapter, server=build_server_settings())

    snapshot = await service.discover()

    assert snapshot.error is None
    assert snapshot.tool_names == ("documents.search", "filesystem.read_project_file")
    assert snapshot.metadata["discovered_tool_count"] == 2


class FailingAdapter:
    async def list_tools(self) -> list[MCPToolDefinition]:
        raise RuntimeError("adapter unavailable")

    async def call_tool(self, *, request: object) -> object:
        raise AssertionError("not used")

    def stream_tool(self, *, request: object) -> object:
        raise AssertionError("not used")

    async def health(self) -> object:
        raise AssertionError("not used")


@pytest.mark.asyncio
async def test_discovery_service_returns_error_snapshot_for_adapter_failure() -> None:
    service = ToolDiscoveryService(mcp_adapter=FailingAdapter(), server=build_server_settings())

    snapshot = await service.discover()

    assert snapshot.tool_count == 0
    assert snapshot.error == "adapter unavailable"
    assert snapshot.metadata["error_type"] == "RuntimeError"
