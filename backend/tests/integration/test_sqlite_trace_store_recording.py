from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts.trace import TraceEvent
from app.persistence.settings import SqliteTraceStoreSettings
from app.persistence.sqlite_trace_store import SqliteTraceStore


@pytest.mark.asyncio
async def test_record_event_persists_summary_and_redacted_payload(tmp_path: Path) -> None:
    database_path = tmp_path / "trace-recording.db"
    store = SqliteTraceStore(database_path, settings=_build_settings(database_path, max_event_payload_bytes=2048))

    await store.initialize()
    await store.record_event(
        TraceEvent(
            trace_id="trace_recording_1",
            session_id="session_123",
            user_id="user_123",
            event_type="request_received",
            component="api.chat",
            timestamp=datetime(2026, 6, 24, 23, 0),
            payload={
                "authorization": "Bearer secret",
                "route_template": "/chat",
                "operation": "chat",
            },
        )
    )

    with sqlite3.connect(database_path) as connection:
        run_row = connection.execute(
            """
            SELECT session_id, session_id_hash, user_id, user_id_hash, operation, route_template, status, event_count, error_count
            FROM trace_runs
            WHERE trace_id = 'trace_recording_1'
            """
        ).fetchone()
        event_row = connection.execute(
            """
            SELECT sequence_no, timestamp, session_id, session_id_hash, user_id, user_id_hash, payload_json
            FROM trace_events
            WHERE trace_id = 'trace_recording_1'
            """
        ).fetchone()

    assert run_row is not None
    assert run_row[0] is None
    assert run_row[1].startswith("sha256:")
    assert run_row[2] is None
    assert run_row[3].startswith("sha256:")
    assert run_row[4:9] == ("chat", "/chat", "completed", 1, 0)
    assert event_row is not None
    assert event_row[0] == 1
    assert event_row[1].endswith("+00:00")
    assert event_row[2] is None
    assert event_row[3].startswith("sha256:")
    assert event_row[4] is None
    assert event_row[5].startswith("sha256:")
    assert json.loads(str(event_row[6])) == {
        "authorization": "***REDACTED***",
        "route_template": "/chat",
        "operation": "chat",
    }


@pytest.mark.asyncio
async def test_record_events_preserves_order_and_updates_summary_counters(tmp_path: Path) -> None:
    database_path = tmp_path / "trace-recording-order.db"
    store = SqliteTraceStore(database_path, settings=_build_settings(database_path))
    started_at = datetime(2026, 6, 24, 23, 0, tzinfo=UTC)

    await store.initialize()
    await store.record_events(
        [
            TraceEvent(
                trace_id="trace_recording_2",
                session_id="session_123",
                event_type="request_received",
                component="api.chat",
                timestamp=started_at,
                status="started",
                payload={"route_template": "/chat"},
            ),
            TraceEvent(
                trace_id="trace_recording_2",
                session_id="session_123",
                event_type="tool_call_failed",
                component="tools.search",
                timestamp=started_at + timedelta(seconds=2),
                status="failed",
                severity="error",
                tool_name="documents.search",
                error_type="ToolTimeoutError",
                duration_ms=2000.0,
            ),
        ]
    )

    with sqlite3.connect(database_path) as connection:
        run_row = connection.execute(
            """
            SELECT status, severity, event_count, error_count, tool_name, error_type, ended_at, duration_ms
            FROM trace_runs
            WHERE trace_id = 'trace_recording_2'
            """
        ).fetchone()
        event_rows = connection.execute(
            """
            SELECT sequence_no, event_name, status, severity
            FROM trace_events
            WHERE trace_id = 'trace_recording_2'
            ORDER BY sequence_no ASC
            """
        ).fetchall()

    assert run_row == ("failed", "error", 2, 1, "documents.search", "ToolTimeoutError", "2026-06-24T23:00:02+00:00", 2000.0)
    assert event_rows == [
        (1, "request_received", "started", "info"),
        (2, "tool_call_failed", "failed", "error"),
    ]


def _build_settings(
    database_path: Path,
    *,
    max_event_payload_bytes: int = 32768,
) -> SqliteTraceStoreSettings:
    return SqliteTraceStoreSettings(
        path=database_path,
        create_parent_dirs=True,
        initialize_schema=True,
        journal_mode="WAL",
        synchronous="NORMAL",
        busy_timeout_ms=5000,
        foreign_keys=True,
        required=True,
        max_event_payload_bytes=max_event_payload_bytes,
        max_error_detail_bytes=256,
        max_events_per_trace_read=1000,
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