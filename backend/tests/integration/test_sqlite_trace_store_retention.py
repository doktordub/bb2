from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts.trace import TraceEvent
from app.persistence.settings import SqliteTraceStoreSettings
from app.persistence.sqlite_trace_store import SqliteTraceStore


@pytest.mark.asyncio
async def test_retention_cleanup_deletes_only_older_trace_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "trace-retention.db"
    store = SqliteTraceStore(database_path, settings=_build_settings(database_path))
    now = datetime.now(UTC)

    await store.initialize()
    await store.record_events(
        [
            TraceEvent(
                trace_id="trace_old_1",
                session_id="session_old_1",
                event_type="request",
                event_name="request_received",
                component="api.http",
                timestamp=now - timedelta(days=30),
            ),
            TraceEvent(
                trace_id="trace_old_2",
                session_id="session_old_2",
                event_type="tool",
                event_name="tool_call_failed",
                component="tools.docs",
                timestamp=now - timedelta(days=20),
                status="failed",
                severity="error",
            ),
            TraceEvent(
                trace_id="trace_new",
                session_id="session_new",
                event_type="request",
                event_name="request_received",
                component="api.http",
                timestamp=now - timedelta(days=1),
            ),
        ]
    )

    result = await store.run_retention_cleanup()

    assert result["status"] == "ok"
    assert result["retention_enabled"] is True
    assert result["deleted_trace_count"] == 2
    assert result["deleted_event_count"] == 2

    with sqlite3.connect(database_path) as connection:
        remaining_trace_ids = connection.execute(
            "SELECT trace_id FROM trace_runs ORDER BY trace_id ASC"
        ).fetchall()
        remaining_event_ids = connection.execute(
            "SELECT trace_id FROM trace_events ORDER BY trace_id ASC"
        ).fetchall()
        retention_rows = connection.execute(
            """
            SELECT status, deleted_trace_count, deleted_event_count
            FROM trace_retention_runs
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()

    assert remaining_trace_ids == [("trace_new",)]
    assert remaining_event_ids == [("trace_new",)]
    assert retention_rows == ("completed", 2, 2)


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
        retention_enabled=True,
        retention_keep_days=14,
        retention_cleanup_batch_size=10,
    )