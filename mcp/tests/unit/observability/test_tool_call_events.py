from __future__ import annotations

import asyncio

from fastmcp.exceptions import ToolError
import pytest

from app.observability.events import (
    MCP_TOOL_CALL_COMPLETED,
    MCP_TOOL_CALL_FAILED,
    MCP_TOOL_CALL_STARTED,
    MCP_TOOL_CALL_TIMEOUT,
)
from app.observability.metrics import InMemoryMetricsRecorder
from app.observability.tracing import InMemoryTraceRecorder
from app.security.redaction import Redactor
from app.tools_base.decorators import observe_tool_call
from tests.unit.observability.support import build_tool_context


async def test_tool_success_emits_safe_events_and_metrics() -> None:
    tracer = InMemoryTraceRecorder(redactor=Redactor())
    metrics = InMemoryMetricsRecorder()
    context = build_tool_context(
        tool_name="demo.echo",
        capability_name="demo.echo",
        metrics=metrics,
        tracer=tracer,
    )

    @observe_tool_call(context, "demo.echo", capability_name="demo.echo")
    async def handler() -> dict[str, object]:
        return {
            "ok": True,
            "result_count": 2,
            "results": [{"title": "one"}, {"title": "two"}],
        }

    result = await handler()

    assert result["ok"] is True
    assert [event.event_name for event in tracer.events] == [
        MCP_TOOL_CALL_STARTED,
        MCP_TOOL_CALL_COMPLETED,
    ]
    completed = tracer.events[-1]
    assert completed.payload["trace_id"].startswith("trace_")
    assert completed.payload["tool_name"] == "demo.echo"
    assert completed.payload["result_count"] == 2
    assert metrics.counter_value(
        "mcp.tool.call.count",
        {
            "tool_name": "demo.echo",
            "capability_name": "demo.echo",
            "status": "ok",
        },
    ) == 1


async def test_tool_safe_error_result_emits_failed_event() -> None:
    tracer = InMemoryTraceRecorder(redactor=Redactor())
    metrics = InMemoryMetricsRecorder()
    context = build_tool_context(
        tool_name="demo.search",
        capability_name="demo.search",
        metrics=metrics,
        tracer=tracer,
    )

    @observe_tool_call(context, "demo.search", capability_name="demo.search")
    async def handler() -> dict[str, object]:
        return {
            "ok": False,
            "error": {
                "code": "provider_unavailable",
                "message": "Provider unavailable.",
            },
            "result_count": 0,
        }

    result = await handler()

    assert result["ok"] is False
    assert [event.event_name for event in tracer.events] == [
        MCP_TOOL_CALL_STARTED,
        MCP_TOOL_CALL_FAILED,
    ]
    failed = tracer.events[-1]
    assert failed.payload["error_code"] == "provider_unavailable"
    assert metrics.counter_value(
        "mcp.tool.error.count",
        {
            "tool_name": "demo.search",
            "capability_name": "demo.search",
            "status": "error",
            "error_code": "provider_unavailable",
        },
    ) == 1


async def test_tool_timeout_emits_timeout_event() -> None:
    tracer = InMemoryTraceRecorder(redactor=Redactor())
    metrics = InMemoryMetricsRecorder()
    context = build_tool_context(
        tool_name="demo.slow",
        capability_name="demo.slow",
        metrics=metrics,
        tracer=tracer,
    )

    @observe_tool_call(
        context,
        "demo.slow",
        capability_name="demo.slow",
        timeout_seconds=0,
    )
    async def handler() -> dict[str, object]:
        await asyncio.sleep(0)
        return {"ok": True}

    with pytest.raises(ToolError, match="timed out"):
        await handler()

    assert [event.event_name for event in tracer.events] == [
        MCP_TOOL_CALL_STARTED,
        MCP_TOOL_CALL_TIMEOUT,
    ]
    assert metrics.counter_value(
        "mcp.tool.timeout.count",
        {
            "tool_name": "demo.slow",
            "capability_name": "demo.slow",
            "status": "timeout",
            "error_code": "timeout",
        },
    ) == 1