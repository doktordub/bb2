from __future__ import annotations

from typing import Any

from app.contracts.tools import ToolExecutionRequest, ToolScopes
from app.tools.errors import MCPTransportError
from app.tools.mcp import FakeMCPClientAdapter, MCPToolCallRequest, MCPToolCallResult, MCPToolContent, MCPToolDefinition


class FlakyReadOnlyAdapter(FakeMCPClientAdapter):
    def __init__(self) -> None:
        super().__init__(
            discovered_tools=[
                MCPToolDefinition(
                    name="documents.search",
                    description="Search indexed documents.",
                    supports_streaming=True,
                ),
                MCPToolDefinition(name="notes.write", description="Write a support note."),
                MCPToolDefinition(name="ops.hidden", description="Hidden operations tool."),
            ],
            endpoint="http://localhost:9001/mcp",
        )
        self.remaining_failures = 1

    async def call_tool(
        self,
        *,
        request: MCPToolCallRequest,
    ) -> MCPToolCallResult:
        self.call_requests.append(request)
        if request.mcp_tool_name == "documents.search" and self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise MCPTransportError("temporary transport failure")
        return MCPToolCallResult(
            mcp_tool_name=request.mcp_tool_name,
            status="completed",
            content=[MCPToolContent(type="text", text="tool completed")],
            structured_content={"ok": True},
            metadata={"provider": "fake"},
        )


async def test_gateway_lists_gets_executes_and_reports_health_capabilities(
    tooling_env_factory,
    tooling_values: dict[str, Any],
) -> None:
    gateway, context, _trace_store, adapter, _runtime, _config = tooling_env_factory(
        tooling_values
    )

    listed = await gateway.list_tools(context)
    resolved = await gateway.get_tool("documents.search", context)
    hidden = await gateway.get_tool("ops.hidden", context)
    result = await gateway.execute(
        ToolExecutionRequest(
            tool_name="documents.search",
            arguments={"query": "phase 5", "limit": 2},
            scopes=ToolScopes(project_id="proj-1"),
        ),
        context,
    )
    health = await gateway.health()
    capabilities = await gateway.capabilities()

    assert [tool.name for tool in listed] == ["documents.search", "notes.write"]
    assert resolved is not None
    assert resolved.name == "documents.search"
    assert resolved.supports_streaming is True
    assert hidden is None
    assert result.success is True
    assert result.structured_content == {"fake": True, "arguments": {"query": "phase 5", "limit": 2}}
    assert len(adapter.call_requests) == 1
    assert adapter.call_requests[0].mcp_tool_name == "documents.search"
    assert adapter.call_requests[0].trace_id == "trace_tool_1"
    assert adapter.call_requests[0].session_id == "session_1"
    assert health.status == "ok"
    assert health["tools_configured"] == 3
    assert health["tools_enabled"] == 3
    assert capabilities["enabled"] is True
    assert capabilities["streaming_supported"] is True
    assert {tool["name"] for tool in capabilities["available_logical_tools"]} == {
        "documents.search",
        "notes.write",
        "ops.hidden",
    }


async def test_gateway_retries_retryable_read_only_execution(
    tooling_env_factory,
    tooling_values: dict[str, Any],
) -> None:
    adapter = FlakyReadOnlyAdapter()
    gateway, context, _trace_store, _adapter, _runtime, _config = tooling_env_factory(
        tooling_values,
        adapter=adapter,
    )

    result = await gateway.execute(
        ToolExecutionRequest(
            tool_name="documents.search",
            arguments={"query": "retry me"},
            scopes=ToolScopes(project_id="proj-1"),
        ),
        context,
    )

    assert result.success is True
    assert len(adapter.call_requests) == 2