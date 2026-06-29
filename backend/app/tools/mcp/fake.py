"""Deterministic fake MCP adapter used by tooling runtime tests and early wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from app.tools.mcp.protocol_models import (
    MCPHealthResult,
    MCPToolCallRequest,
    MCPToolCallResult,
    MCPToolContent,
    MCPToolDefinition,
    MCPToolStreamEvent,
)
from app.tools.models import ToolRegistryEntry


class FakeMCPClientAdapter:
    """Deterministic MCP client adapter with configurable fake discovery and results."""

    def __init__(
        self,
        discovered_tools: Sequence[MCPToolDefinition] | None = None,
        *,
        execution_results: Mapping[str, MCPToolCallResult] | None = None,
        stream_events: Mapping[str, Sequence[MCPToolStreamEvent]] | None = None,
        enabled: bool = True,
        endpoint: str | None = None,
        auth_mode: str = "none",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.discovered_tools = list(discovered_tools or ())
        self.execution_results = dict(execution_results or {})
        self.stream_events = {
            tool_name: tuple(events)
            for tool_name, events in dict(stream_events or {}).items()
        }
        self.enabled = enabled
        self.endpoint = endpoint
        self.auth_mode = auth_mode
        self.metadata = dict(metadata or {})
        self.list_calls = 0
        self.call_requests: list[MCPToolCallRequest] = []
        self.stream_requests: list[MCPToolCallRequest] = []

    @classmethod
    def from_registry_entries(
        cls,
        *,
        registry_entries: Mapping[str, ToolRegistryEntry] | Sequence[ToolRegistryEntry],
        enabled: bool = True,
        endpoint: str | None = None,
        auth_mode: str = "none",
        metadata: Mapping[str, Any] | None = None,
    ) -> "FakeMCPClientAdapter":
        entries = (
            registry_entries.values()
            if isinstance(registry_entries, Mapping)
            else registry_entries
        )
        discovered_tools = [
            MCPToolDefinition(
                name=entry.mcp_tool_name,
                description=entry.definition.description,
                input_schema=entry.definition.input_schema or {},
                output_schema=entry.definition.output_schema,
                supports_streaming=entry.definition.supports_streaming,
                metadata={"logical_name": entry.logical_name},
            )
            for entry in entries
            if entry.definition.enabled
        ]
        return cls(
            discovered_tools=discovered_tools,
            enabled=enabled,
            endpoint=endpoint,
            auth_mode=auth_mode,
            metadata=metadata,
        )

    async def list_tools(self) -> list[MCPToolDefinition]:
        self.list_calls += 1
        return list(self.discovered_tools)

    async def call_tool(
        self,
        *,
        request: MCPToolCallRequest,
    ) -> MCPToolCallResult:
        self.call_requests.append(request)
        return self._resolve_result(request)

    async def stream_tool(
        self,
        *,
        request: MCPToolCallRequest,
    ) -> AsyncIterator[MCPToolStreamEvent]:
        self.stream_requests.append(request)
        configured_events = self.stream_events.get(request.mcp_tool_name)
        if configured_events is not None:
            for event in configured_events:
                yield event
            return

        result = self._resolve_result(request)
        yield MCPToolStreamEvent.started(mcp_tool_name=request.mcp_tool_name)
        for item in result.content:
            if item.type == "text" and item.text:
                yield MCPToolStreamEvent.delta(
                    mcp_tool_name=request.mcp_tool_name,
                    text=item.text,
                )

        if result.status == "completed":
            yield MCPToolStreamEvent.completed(
                mcp_tool_name=request.mcp_tool_name,
                result=result,
            )
            return
        if result.status == "cancelled":
            yield MCPToolStreamEvent.cancelled(mcp_tool_name=request.mcp_tool_name)
            return

        yield MCPToolStreamEvent.error_event(
            mcp_tool_name=request.mcp_tool_name,
            error_message=result.error_message or "Fake MCP tool execution failed.",
        )

    async def health(self) -> MCPHealthResult:
        return MCPHealthResult(
            status="ok" if self.enabled else "disabled",
            configured=self.endpoint is not None,
            endpoint=self.endpoint,
            auth_mode=self.auth_mode,
            tool_count=len(self.discovered_tools),
            metadata={"provider": "fake", **self.metadata},
        )

    def _resolve_result(self, request: MCPToolCallRequest) -> MCPToolCallResult:
        configured = self.execution_results.get(request.mcp_tool_name)
        if configured is not None:
            return configured
        return MCPToolCallResult(
            mcp_tool_name=request.mcp_tool_name,
            status="completed",
            content=[
                MCPToolContent(
                    type="text",
                    text=f"Fake MCP tool call completed: {request.mcp_tool_name}",
                )
            ],
            structured_content={"fake": True, "arguments": dict(request.arguments)},
            metadata={"provider": "fake"},
        )