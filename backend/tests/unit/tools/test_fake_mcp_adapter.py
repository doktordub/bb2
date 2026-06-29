from __future__ import annotations

from app.tools.mcp import (
    FakeMCPClientAdapter,
    MCPToolCallRequest,
    MCPToolCallResult,
    MCPToolContent,
    MCPToolDefinition,
)


async def test_fake_mcp_adapter_lists_discovered_tools() -> None:
    adapter = FakeMCPClientAdapter(
        discovered_tools=[
            MCPToolDefinition(name="documents.search"),
            MCPToolDefinition(name="filesystem.read_project_file", supports_streaming=True),
        ],
        endpoint="http://localhost:9001/mcp",
    )

    discovered = await adapter.list_tools()

    assert [tool.name for tool in discovered] == [
        "documents.search",
        "filesystem.read_project_file",
    ]
    assert adapter.list_calls == 1


async def test_fake_mcp_adapter_executes_configured_tool_calls() -> None:
    request = MCPToolCallRequest(
        mcp_tool_name="documents.search",
        arguments={"query": "backend tooling"},
        timeout_seconds=30,
        trace_id="trace-123",
    )
    adapter = FakeMCPClientAdapter(
        execution_results={
            "documents.search": MCPToolCallResult(
                mcp_tool_name="documents.search",
                status="completed",
                content=[MCPToolContent(type="text", text="1 result")],
                structured_content={"count": 1},
            )
        }
    )

    result = await adapter.call_tool(request=request)

    assert result.success is True
    assert result.structured_content == {"count": 1}
    assert adapter.call_requests == [request]


async def test_fake_mcp_adapter_streams_default_incremental_events() -> None:
    request = MCPToolCallRequest(
        mcp_tool_name="filesystem.read_project_file",
        arguments={"path": "README.md"},
        timeout_seconds=30,
        trace_id="trace-456",
    )
    adapter = FakeMCPClientAdapter(
        execution_results={
            "filesystem.read_project_file": MCPToolCallResult(
                mcp_tool_name="filesystem.read_project_file",
                status="completed",
                content=[
                    MCPToolContent(type="text", text="chunk one"),
                    MCPToolContent(type="text", text="chunk two"),
                ],
            )
        }
    )

    events = [event async for event in adapter.stream_tool(request=request)]

    assert [event.type for event in events] == ["started", "delta", "delta", "completed"]
    assert [event.text for event in events[1:3]] == ["chunk one", "chunk two"]
    assert events[-1].result is not None
    assert adapter.stream_requests == [request]


async def test_fake_mcp_adapter_reports_safe_health_summary() -> None:
    adapter = FakeMCPClientAdapter(
        discovered_tools=[MCPToolDefinition(name="documents.search")],
        endpoint="http://localhost:9001/mcp",
        auth_mode="bearer",
        metadata={"server_name": "fake_main"},
    )

    health = await adapter.health()

    assert health.status == "ok"
    assert health.configured is True
    assert health.auth_mode == "bearer"
    assert health.tool_count == 1
    assert health.metadata["provider"] == "fake"
    assert health.metadata["server_name"] == "fake_main"