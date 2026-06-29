from __future__ import annotations

from typing import Any

from app.contracts.tools import ToolExecutionRequest, ToolScopes
from app.contracts.trace import TOOL_CALL_COMPLETED, TOOL_CALL_STARTED
from app.tools.mcp import (
    FakeMCPClientAdapter,
    MCPToolCallResult,
    MCPToolContent,
    MCPToolDefinition,
    MCPToolStreamEvent,
)


async def test_gateway_streams_events_and_records_safe_trace_events(
    tooling_env_factory,
    tooling_values: dict[str, Any],
) -> None:
    adapter = FakeMCPClientAdapter(
        discovered_tools=[
            MCPToolDefinition(
                name="documents.search",
                description="Search indexed documents.",
                supports_streaming=True,
            )
        ],
        stream_events={
            "documents.search": (
                MCPToolStreamEvent.started(mcp_tool_name="documents.search"),
                MCPToolStreamEvent.delta(
                    mcp_tool_name="documents.search",
                    text="chunk-1",
                ),
                MCPToolStreamEvent.completed(
                    mcp_tool_name="documents.search",
                    result=MCPToolCallResult(
                        mcp_tool_name="documents.search",
                        status="completed",
                        content=[MCPToolContent(type="text", text="complete")],
                        structured_content={"done": True},
                    ),
                ),
            )
        },
        endpoint="http://localhost:9001/mcp",
    )
    gateway, context, trace_store, _adapter, _runtime, _config = tooling_env_factory(
        tooling_values,
        adapter=adapter,
    )

    events = [
        event
        async for event in gateway.stream_execute(
            ToolExecutionRequest(
                tool_name="documents.search",
                arguments={"query": "stream this"},
                scopes=ToolScopes(project_id="proj-1"),
                stream=True,
            ),
            context,
        )
    ]

    assert [event.type for event in events] == ["started", "delta", "completed"]
    assert trace_store.events[0].event_type == TOOL_CALL_STARTED
    assert trace_store.events[1].event_type == TOOL_CALL_COMPLETED
    assert "arguments" not in trace_store.events[0].payload
    assert "chunk-1" not in str(trace_store.events[1].payload)