from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.contracts.trace import TraceEvent, TraceSearchFilters
from app.testing.fakes.fake_trace import FakeTraceStore


def build_event(
    *,
    trace_id: str,
    timestamp: datetime,
    event_type: str,
    event_name: str,
    status: str = "completed",
    severity: str = "info",
    session_id: str = "session_1",
    session_id_hash: str | None = "sha256:session_1",
    user_id_hash: str | None = "sha256:user_1",
    usecase: str | None = "default_chat",
    agent_name: str | None = None,
    strategy_name: str | None = None,
    llm_profile: str | None = None,
    tool_name: str | None = None,
    duration_ms: float | None = None,
    error_type: str | None = None,
    payload: dict[str, object] | None = None,
) -> TraceEvent:
    return TraceEvent(
        trace_id=trace_id,
        session_id=session_id,
        session_id_hash=session_id_hash,
        user_id_hash=user_id_hash,
        event_type=event_type,
        event_name=event_name,
        component="tests.fake_trace",
        timestamp=timestamp,
        status=status,
        severity=severity,
        usecase=usecase,
        agent_name=agent_name,
        strategy_name=strategy_name,
        llm_profile=llm_profile,
        tool_name=tool_name,
        duration_ms=duration_ms,
        error_type=error_type,
        payload=payload or {},
    )


@pytest.mark.asyncio
async def test_fake_trace_store_records_batches_and_reads_trace_summary() -> None:
    store = FakeTraceStore()
    started_at = datetime(2026, 6, 24, 23, 0, tzinfo=UTC)
    events = [
        build_event(
            trace_id="trace_1",
            timestamp=started_at,
            event_type="request",
            event_name="request_received",
            status="started",
            payload={"route_template": "/chat"},
        ),
        build_event(
            trace_id="trace_1",
            timestamp=started_at + timedelta(seconds=1),
            event_type="tool",
            event_name="tool_call_failed",
            status="failed",
            severity="error",
            tool_name="documents.search",
            error_type="ToolTimeoutError",
            duration_ms=1000.0,
        ),
    ]

    await store.record_events(events)
    trace = await store.read_trace(trace_id="trace_1")

    assert trace.found is True
    assert trace.trace_id == "trace_1"
    assert trace.status == "failed"
    assert trace.severity == "error"
    assert trace.event_count == 2
    assert trace.error_count == 1
    assert trace.usecase == "default_chat"
    assert trace.tool_name == "documents.search"
    assert [event.resolved_event_name for event in trace.events] == [
        "request_received",
        "tool_call_failed",
    ]


@pytest.mark.asyncio
async def test_fake_trace_store_read_limit_preserves_total_event_count() -> None:
    store = FakeTraceStore()
    started_at = datetime(2026, 6, 24, 23, 0, tzinfo=UTC)
    await store.record_events(
        [
            build_event(
                trace_id="trace_2",
                timestamp=started_at + timedelta(seconds=index),
                event_type="request",
                event_name=f"event_{index}",
            )
            for index in range(3)
        ]
    )

    trace = await store.read_trace(trace_id="trace_2", limit=2)

    assert trace.found is True
    assert trace.event_count == 3
    assert len(trace.events) == 2
    assert [event.resolved_event_name for event in trace.events] == ["event_0", "event_1"]


@pytest.mark.asyncio
async def test_fake_trace_store_search_applies_trace_filters() -> None:
    store = FakeTraceStore()
    started_at = datetime(2026, 6, 24, 23, 0, tzinfo=UTC)

    await store.record_event(
        build_event(
            trace_id="trace_ok",
            timestamp=started_at,
            event_type="request",
            event_name="request_received",
            session_id_hash="sha256:session_ok",
        )
    )
    await store.record_event(
        build_event(
            trace_id="trace_failed",
            timestamp=started_at + timedelta(minutes=1),
            event_type="tool",
            event_name="tool_call_failed",
            status="failed",
            severity="error",
            tool_name="documents.search",
            error_type="ToolTimeoutError",
            session_id_hash="sha256:session_failed",
        )
    )

    results = await store.search_traces(
        filters=TraceSearchFilters(
            errors_only=True,
            event_name="tool_call_failed",
            session_id_hash="sha256:session_failed",
            limit=10,
        )
    )

    assert [summary.trace_id for summary in results] == ["trace_failed"]
    assert results[0].error_count == 1
    assert results[0].tool_name == "documents.search"


@pytest.mark.asyncio
async def test_fake_trace_store_search_defaults_to_bounded_limit() -> None:
    store = FakeTraceStore()
    started_at = datetime(2026, 6, 24, 23, 0, tzinfo=UTC)

    for index in range(105):
        await store.record_event(
            build_event(
                trace_id=f"trace_{index}",
                timestamp=started_at + timedelta(minutes=index),
                event_type="request",
                event_name="request_received",
                session_id=f"session_{index}",
                session_id_hash=f"sha256:session_{index}",
                user_id_hash=f"sha256:user_{index}",
            )
        )

    results = await store.search_traces(filters=TraceSearchFilters())

    assert len(results) == 100
    assert results[0].trace_id == "trace_104"
    assert results[-1].trace_id == "trace_5"