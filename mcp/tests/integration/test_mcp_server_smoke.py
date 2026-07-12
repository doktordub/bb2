from __future__ import annotations

import os

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.utilities.tests import run_server_async
import pytest

from app.bootstrap import bootstrap
from app.observability.events import MCP_TOOL_CALL_COMPLETED, MCP_TOOL_CALL_STARTED
from app.observability.tracing import InMemoryTraceRecorder


@pytest.mark.asyncio
async def test_mcp_http_server_exposes_expected_tools_and_trace_correlation() -> None:
    runtime = bootstrap()
    assert isinstance(runtime.services.tracer, InMemoryTraceRecorder)

    trace_id = "trace-mcp-http-smoke-0001"
    transport = None
    async with run_server_async(runtime.server) as url:
        transport = StreamableHttpTransport(url, headers={"x-trace-id": trace_id})
        async with Client(transport) as client:
            tools = await client.list_tools()
            capabilities = await client.call_tool("mcp.capabilities", {})
            health = await client.call_tool("mcp.health", {})

    tool_names = {tool.name for tool in tools}
    assert {"mcp.capabilities", "mcp.health", "mcp.tools.list", "websearch.search"}.issubset(
        tool_names
    )

    capability_payload = capabilities.structured_content
    assert isinstance(capability_payload, dict)
    capability_entry = next(
        item
        for item in capability_payload["capabilities"]
        if item["tool_name"] == "websearch.search"
    )
    assert capability_entry == {
        "capability_name": "web.search",
        "type": "tool",
        "tool_name": "websearch.search",
        "risk_level": "read_only",
        "enabled": True,
        "status": "loaded",
        "health": "ok",
        "version": "1.0.0",
        "owner": "platform",
        "tags": ["read_only", "search", "web"],
        "input_schema": "auto",
        "output_schema": "structured_results",
        "schema_version": None,
    }

    health_payload = health.structured_content
    assert isinstance(health_payload, dict)
    assert health_payload["ready"] is True
    assert health_payload["tools"]["loaded"] >= 1
    assert health_payload["checks"]["websearch_local_readiness"] in {"ok", "degraded"}

    trace_events = [
        event
        for event in runtime.services.tracer.events
        if event.event_name in {MCP_TOOL_CALL_STARTED, MCP_TOOL_CALL_COMPLETED}
    ]
    assert any(
        event.payload.get("tool_name") == "mcp.capabilities"
        and event.payload.get("trace_id") == trace_id
        for event in trace_events
    )
    assert all("authorization" not in event.payload for event in runtime.services.tracer.events)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.external_network
@pytest.mark.skipif(
    os.getenv("BB2_RUN_EXTERNAL_MCP_WEBSEARCH_TESTS") != "1",
    reason="External-network MCP websearch smoke tests are opt-in.",
)
async def test_mcp_http_server_executes_live_websearch_tool() -> None:
    runtime = bootstrap()

    async with run_server_async(runtime.server) as url:
        transport = StreamableHttpTransport(
            url,
            headers={"x-trace-id": "trace-mcp-websearch-live-0001"},
        )
        async with Client(transport) as client:
            result = await client.call_tool(
                "websearch.search",
                {
                    "query": "Python FastMCP",
                    "max_results": 2,
                },
                timeout=30,
            )

    payload = result.structured_content
    assert isinstance(payload, dict)
    assert payload["result_count"] <= 2
    assert len(payload["results"]) <= 2
    if payload["ok"] is True:
        assert payload["results"]
        for item in payload["results"]:
            assert set(item) >= {"rank", "title", "url", "snippet", "source"}
        return

    assert payload["results"] == []
    assert payload["error"] == {
        "code": "provider_unavailable",
        "message": "Web search provider is unavailable.",
        "retryable": True,
    }