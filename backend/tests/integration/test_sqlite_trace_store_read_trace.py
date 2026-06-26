from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts.trace import TraceEvent
from app.persistence.settings import SqliteTraceStoreSettings
from app.persistence.sqlite_trace_store import SqliteTraceStore


@pytest.mark.asyncio
async def test_read_trace_returns_ordered_events_and_preserves_summary_counts(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "trace-read.db"
    store = SqliteTraceStore(database_path, settings=_build_settings(database_path))
    started_at = datetime(2026, 6, 25, 10, 0, tzinfo=UTC)

    await store.initialize()
    await store.record_events(
        [
            TraceEvent(
                trace_id="trace_read_1",
                session_id="session_1",
                event_type="request",
                event_name="request_received",
                component="api.http",
                timestamp=started_at,
                status="started",
                payload={"route_template": "/chat", "operation": "chat"},
            ),
            TraceEvent(
                trace_id="trace_read_1",
                session_id="session_1",
                event_type="tool",
                event_name="tool_call_completed",
                component="tools.docs",
                timestamp=started_at + timedelta(seconds=1),
                tool_name="documents.search",
            ),
            TraceEvent(
                trace_id="trace_read_1",
                session_id="session_1",
                event_type="response",
                event_name="response_returned",
                component="api.http",
                timestamp=started_at + timedelta(seconds=2),
                duration_ms=2000.0,
            ),
        ]
    )

    trace = await store.read_trace(trace_id="trace_read_1", limit=2)

    assert trace.found is True
    assert trace.trace_id == "trace_read_1"
    assert trace.operation == "chat"
    assert trace.route_template == "/chat"
    assert trace.event_count == 3
    assert len(trace.events) == 2
    assert [event.resolved_event_name for event in trace.events] == [
        "request_received",
        "tool_call_completed",
    ]


@pytest.mark.asyncio
async def test_read_trace_returns_not_found_model_for_unknown_trace(tmp_path: Path) -> None:
    database_path = tmp_path / "trace-read-not-found.db"
    store = SqliteTraceStore(database_path, settings=_build_settings(database_path))

    await store.initialize()

    trace = await store.read_trace(trace_id="trace_missing")

    assert trace.found is False
    assert trace.trace_id == "trace_missing"
    assert trace.event_count == 0
    assert trace.events == ()


def _build_settings(database_path: Path) -> SqliteTraceStoreSettings:
    return SqliteTraceStoreSettings(
        path=database_path,
        create_parent_dirs=True,
        initialize_schema=True,
        journal_mode="WAL",
        synchronous="NORMAL",
        busy_timeout_ms=5000,
        foreign_keys=True,
        required=True,
        max_event_payload_bytes=32768,
        max_error_detail_bytes=4096,
        max_events_per_trace_read=50,
        max_search_results=200,
        store_raw_session_id=False,
        store_session_id_hash=True,
        store_raw_user_id=False,
        store_user_id_hash=True,
        capture_request_body=False,
        capture_response_body=False,
        capture_llm_prompts=False,
        capture_llm_completions=False,
        capture_tool_payloads="summaries_only",
        capture_memory_queries="summaries_only",
        retention_enabled=False,
        retention_keep_days=30,
        retention_cleanup_batch_size=1000,
    )