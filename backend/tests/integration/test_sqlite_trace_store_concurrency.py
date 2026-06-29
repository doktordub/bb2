from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts.trace import TraceEvent
from app.persistence.settings import SqliteTraceStoreSettings
from app.persistence.sqlite.connection import open_sqlite_connection
from app.persistence.sqlite_trace_store import SqliteTraceStore


@pytest.mark.asyncio
async def test_sqlite_trace_store_concurrent_writes_preserve_per_trace_sequence_numbers(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "trace-concurrency.db"
    store = SqliteTraceStore(database_path, settings=_build_settings(database_path))
    started_at = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)
    events = [
        TraceEvent(
            trace_id="trace_concurrency_1",
            session_id="session_1",
            event_type="request_received",
            component="api.chat",
            timestamp=started_at + timedelta(milliseconds=index),
            status="started" if index == 0 else "completed",
            payload={"operation": "chat", "ordinal": index},
        )
        for index in range(10)
    ]

    await store.initialize()
    await asyncio.gather(*(store.record_event(event) for event in events))

    with open_sqlite_connection(database_path, settings=store.settings) as connection:
        event_rows = connection.execute(
            """
            SELECT sequence_no, timestamp, status
            FROM trace_events
            WHERE trace_id = ?
            ORDER BY sequence_no ASC
            """,
            ("trace_concurrency_1",),
        ).fetchall()
        run_row = connection.execute(
            """
            SELECT event_count, error_count, status, operation
            FROM trace_runs
            WHERE trace_id = ?
            """,
            ("trace_concurrency_1",),
        ).fetchone()
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
        synchronous = connection.execute("PRAGMA synchronous").fetchone()
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()

    assert len(event_rows) == len(events)
    assert [row[0] for row in event_rows] == list(range(1, len(events) + 1))
    assert sorted(row[1] for row in event_rows) == [event.timestamp.isoformat() for event in events]
    assert {row[2] for row in event_rows} == {"completed", "started"}

    assert run_row is not None
    assert run_row[0] == 10
    assert run_row[1] == 0
    assert run_row[2] in {"started", "completed"}
    assert run_row[3] == "chat"
    assert journal_mode is not None
    assert str(journal_mode[0]).lower() == "wal"
    assert synchronous == (1,)
    assert busy_timeout == (5000,)
    assert foreign_keys == (1,)


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
        retention_enabled=False,
        retention_keep_days=30,
        retention_cleanup_batch_size=1000,
    )