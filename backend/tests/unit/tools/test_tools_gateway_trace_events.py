from __future__ import annotations

from typing import Any

import pytest

from app.contracts.tools import ToolExecutionRequest, ToolScopes
from app.contracts.trace import TOOL_CALL_FAILED, TOOL_CALL_STARTED
from app.tools.errors import ToolPolicyDeniedError
from app.tools.mcp import FakeMCPClientAdapter, MCPToolCallResult, MCPToolContent, MCPToolDefinition


async def test_gateway_records_safe_trace_events_without_raw_arguments_or_results(
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
        execution_results={
            "documents.search": MCPToolCallResult(
                mcp_tool_name="documents.search",
                status="completed",
                content=[MCPToolContent(type="text", text="Sensitive raw output")],
                structured_content={
                    "documents": [
                        {"title": "Internal Memo", "snippet": "Top secret result"}
                    ]
                },
            )
        },
        endpoint="http://localhost:9001/mcp",
    )
    gateway, context, trace_store, _adapter, _runtime, _config = tooling_env_factory(
        tooling_values,
        adapter=adapter,
    )

    result = await gateway.execute(
        ToolExecutionRequest(
            tool_name="documents.search",
            arguments={"query": "phase five"},
            scopes=ToolScopes(project_id="proj-1"),
        ),
        context,
    )

    assert result.success is True
    assert trace_store.events[0].event_type == TOOL_CALL_STARTED
    assert "arguments" not in trace_store.events[0].payload
    assert "phase five" not in str(trace_store.events[0].payload)
    assert "Sensitive raw output" not in str(trace_store.events[1].payload)
    assert "Top secret result" not in str(trace_store.events[1].payload)


async def test_gateway_records_failure_trace_for_policy_denial(
    tooling_env_factory,
    tooling_values: dict[str, Any],
) -> None:
    gateway, context, trace_store, adapter, _runtime, _config = tooling_env_factory(
        tooling_values,
        usecase="admin_only",
    )

    with pytest.raises(ToolPolicyDeniedError):
        await gateway.execute(
            ToolExecutionRequest(
                tool_name="documents.search",
                arguments={"query": "blocked"},
                scopes=ToolScopes(project_id="proj-1"),
            ),
            context,
        )

    assert getattr(adapter, "call_requests", []) == []
    assert trace_store.events[-1].event_type == TOOL_CALL_FAILED
    assert "blocked" not in str(trace_store.events[-1].payload)