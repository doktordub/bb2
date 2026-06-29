from __future__ import annotations

import asyncio

import pytest

from app.config.view import MCPAuthSettings, MCPServerSettings
from app.tools.mcp import DefaultMCPClientAdapter
from app.tools.mcp.protocol_models import MCPHealthResult, MCPToolCallRequest


class CancelledTransport:
    async def request(
        self,
        *,
        method: str,
        payload: dict[str, object],
        timeout_seconds: int,
    ) -> dict[str, object]:
        raise asyncio.CancelledError()

    async def stream(
        self,
        *,
        method: str,
        payload: dict[str, object],
        timeout_seconds: int,
    ):
        raise asyncio.CancelledError()
        yield {}

    async def health(self) -> MCPHealthResult:
        return MCPHealthResult(
            status="ok",
            configured=True,
            endpoint="http://localhost:9001/mcp",
            auth_mode="none",
            tool_count=0,
        )


def _server_settings() -> MCPServerSettings:
    return MCPServerSettings(
        name="main",
        enabled=True,
        endpoint="http://localhost:9001/mcp",
        transport="http",
        timeout_seconds=30,
        stream_timeout_seconds=60,
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


async def test_client_adapter_propagates_cancellation_for_call_tool() -> None:
    adapter = DefaultMCPClientAdapter(
        server=_server_settings(),
        transport=CancelledTransport(),
    )

    with pytest.raises(asyncio.CancelledError):
        await adapter.call_tool(
            request=MCPToolCallRequest(
                mcp_tool_name="documents.search",
                arguments={"query": "backend tooling"},
                timeout_seconds=10,
                trace_id="trace-123",
            )
        )


async def test_client_adapter_propagates_cancellation_for_stream_tool() -> None:
    adapter = DefaultMCPClientAdapter(
        server=_server_settings(),
        transport=CancelledTransport(),
    )

    with pytest.raises(asyncio.CancelledError):
        async for _event in adapter.stream_tool(
            request=MCPToolCallRequest(
                mcp_tool_name="documents.search",
                arguments={"query": "backend tooling"},
                timeout_seconds=10,
                trace_id="trace-123",
            )
        ):
            pass