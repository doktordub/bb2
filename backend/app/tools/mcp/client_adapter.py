"""Concrete backend-owned MCP client adapter for the tooling runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import mcp.types as mcp_types
from pydantic import ValidationError

from app.config.view import MCPServerSettings
from app.tools.errors import MCPTransportError
from app.tools.mcp.auth import MCPAuthProvider, build_mcp_auth_provider
from app.tools.mcp.errors import map_mcp_exception
from app.tools.mcp.event_stream import (
    call_tool_result_to_result,
    tool_to_definition,
    transport_payload_to_event,
)
from app.tools.mcp.protocol_models import (
    MCPHealthResult,
    MCPToolCallRequest,
    MCPToolCallResult,
    MCPToolDefinition,
    MCPToolStreamEvent,
)
from app.tools.mcp.transport import DefaultMCPTransport, MCPTransport


class DefaultMCPClientAdapter:
    """Adapter that hides MCP library details behind backend-owned DTOs."""

    def __init__(
        self,
        *,
        server: MCPServerSettings,
        transport: MCPTransport | None = None,
        auth_provider: MCPAuthProvider | None = None,
    ) -> None:
        self._server = server
        self._auth_provider = auth_provider or build_mcp_auth_provider(
            server.auth,
            timeout_seconds=min(server.timeout_seconds, 15),
        )
        self._transport = transport or DefaultMCPTransport(
            endpoint=server.endpoint,
            transport=server.transport,
            auth_provider=self._auth_provider,
            auth_mode=server.auth.mode,
            default_timeout_seconds=server.timeout_seconds,
            default_stream_timeout_seconds=server.stream_timeout_seconds,
        )

    async def list_tools(self) -> list[MCPToolDefinition]:
        if not self._server.enabled:
            return []
        self._ensure_available()
        payload = await self._transport.request(
            method="tools/list",
            payload={},
            timeout_seconds=self._server.timeout_seconds,
        )
        try:
            result = mcp_types.ListToolsResult.model_validate(payload)
        except ValidationError as exc:
            mapped = map_mcp_exception(exc)
            raise mapped from exc
        return [tool_to_definition(tool) for tool in result.tools]

    async def call_tool(
        self,
        *,
        request: MCPToolCallRequest,
    ) -> MCPToolCallResult:
        self._ensure_available()
        payload = await self._transport.request(
            method="tools/call",
            payload={
                "name": request.mcp_tool_name,
                "arguments": dict(request.arguments),
                "meta": _request_meta(request),
            },
            timeout_seconds=max(1, request.timeout_seconds),
        )
        try:
            result = mcp_types.CallToolResult.model_validate(payload)
        except ValidationError as exc:
            mapped = map_mcp_exception(exc)
            raise mapped from exc
        return call_tool_result_to_result(request.mcp_tool_name, result)

    async def stream_tool(
        self,
        *,
        request: MCPToolCallRequest,
    ) -> AsyncIterator[MCPToolStreamEvent]:
        self._ensure_available()
        async for payload in self._transport.stream(
            method="tools/call",
            payload={
                "name": request.mcp_tool_name,
                "arguments": dict(request.arguments),
                "meta": _request_meta(request),
            },
            timeout_seconds=max(1, request.timeout_seconds),
        ):
            yield transport_payload_to_event(request.mcp_tool_name, payload)

    async def health(self) -> MCPHealthResult:
        if not self._server.enabled:
            return MCPHealthResult(
                status="disabled",
                configured=bool(self._server.endpoint),
                endpoint=self._server.endpoint,
                auth_mode=self._server.auth.mode,
                tool_count=0,
                metadata={
                    "server_name": self._server.name,
                    "transport": self._server.transport,
                    "tool_discovery_enabled": self._server.tool_discovery_enabled,
                },
            )
        if self._server.endpoint is None:
            return MCPHealthResult(
                status="not_configured",
                configured=False,
                endpoint=None,
                auth_mode=self._server.auth.mode,
                tool_count=0,
                metadata={
                    "server_name": self._server.name,
                    "transport": self._server.transport,
                    "tool_discovery_enabled": self._server.tool_discovery_enabled,
                },
            )

        health = await self._transport.health()
        merged_metadata = {
            **health.metadata,
            "server_name": self._server.name,
            "tool_discovery_enabled": self._server.tool_discovery_enabled,
        }
        return MCPHealthResult(
            status=health.status,
            configured=health.configured,
            endpoint=health.endpoint,
            auth_mode=health.auth_mode,
            tool_count=health.tool_count,
            error=health.error,
            metadata=merged_metadata,
        )

    def _ensure_available(self) -> None:
        if not self._server.enabled:
            raise MCPTransportError("The configured MCP server is disabled.")
        if self._server.endpoint is None:
            raise MCPTransportError("The MCP endpoint is not configured.")


def _request_meta(request: MCPToolCallRequest) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "trace_id": request.trace_id,
        **dict(request.metadata),
    }
    if request.session_id is not None:
        meta["session_id"] = request.session_id
    if request.idempotency_key is not None:
        meta["idempotency_key"] = request.idempotency_key

    return {
        str(key): value
        for key, value in meta.items()
        if value is not None and isinstance(key, str)
    }


__all__ = ["DefaultMCPClientAdapter"]