from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import mcp.types as mcp_types

from app.tools.mcp import DefaultMCPTransport, NoOpMCPAuthProvider


class FakeTransportSession:
    def __init__(self) -> None:
        self.call_args: list[tuple[str, dict[str, Any] | None, dict[str, Any] | None, timedelta | None]] = []
        self.ping_calls = 0

    async def list_tools(self, cursor: str | None = None, *, params: Any = None) -> mcp_types.ListToolsResult:
        assert cursor is None
        assert params is None
        return mcp_types.ListToolsResult(
            tools=[
                mcp_types.Tool(
                    name="documents.search",
                    description="Search indexed documents.",
                    inputSchema={"type": "object"},
                )
            ]
        )

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: timedelta | None = None,
        progress_callback: Any = None,
        *,
        meta: dict[str, Any] | None = None,
    ) -> mcp_types.CallToolResult:
        self.call_args.append((name, arguments, meta, read_timeout_seconds))
        if progress_callback is not None:
            await progress_callback(0.5, 1.0, "halfway")
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="1 result")],
            structuredContent={"count": 1},
        )

    async def send_ping(self) -> mcp_types.EmptyResult:
        self.ping_calls += 1
        return mcp_types.EmptyResult()


async def test_transport_request_and_health_use_configured_session_factory() -> None:
    session = FakeTransportSession()
    opened: list[tuple[int, int]] = []

    @asynccontextmanager
    async def session_factory(*, timeout_seconds: int, stream_timeout_seconds: int):
        opened.append((timeout_seconds, stream_timeout_seconds))
        yield session

    transport = DefaultMCPTransport(
        endpoint="http://localhost:9001/mcp",
        transport="http",
        auth_provider=NoOpMCPAuthProvider(),
        auth_mode="none",
        default_timeout_seconds=30,
        default_stream_timeout_seconds=90,
        session_factory=session_factory,
    )

    tools_payload = await transport.request(
        method="tools/list",
        payload={},
        timeout_seconds=12,
    )
    call_payload = await transport.request(
        method="tools/call",
        payload={
            "name": "documents.search",
            "arguments": {"query": "backend tooling"},
            "meta": {"trace_id": "trace-123"},
        },
        timeout_seconds=15,
    )
    health = await transport.health()

    assert tools_payload["tools"][0]["name"] == "documents.search"
    assert call_payload["structuredContent"] == {"count": 1}
    assert session.call_args == [
        (
            "documents.search",
            {"query": "backend tooling"},
            {"trace_id": "trace-123"},
            timedelta(seconds=15),
        )
    ]
    assert session.ping_calls == 1
    assert health.status == "ok"
    assert opened == [(12, 90), (15, 90), (30, 90)]


async def test_transport_stream_emits_started_progress_and_completed_events() -> None:
    session = FakeTransportSession()

    @asynccontextmanager
    async def session_factory(*, timeout_seconds: int, stream_timeout_seconds: int):
        assert timeout_seconds == 20
        assert stream_timeout_seconds == 60
        yield session

    transport = DefaultMCPTransport(
        endpoint="http://localhost:9001/mcp",
        transport="http",
        auth_provider=NoOpMCPAuthProvider(),
        auth_mode="none",
        default_timeout_seconds=20,
        default_stream_timeout_seconds=60,
        session_factory=session_factory,
    )

    events = [
        event
        async for event in transport.stream(
            method="tools/call",
            payload={
                "name": "documents.search",
                "arguments": {"query": "backend tooling"},
                "meta": {"trace_id": "trace-123"},
            },
            timeout_seconds=20,
        )
    ]

    assert [event["type"] for event in events] == ["started", "progress", "completed"]
    assert events[1]["progress"] == 0.5
    assert events[1]["message"] == "halfway"
    assert events[2]["result"]["structuredContent"] == {"count": 1}