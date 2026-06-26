from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts.trace import TraceEvent
from app.persistence.errors import TraceStoreValidationError
from app.persistence.settings import SqliteTraceStoreSettings
from app.persistence.sqlite_trace_store import SqliteTraceStore


@pytest.mark.asyncio
async def test_record_events_commits_a_batch_for_multiple_traces(tmp_path: Path) -> None:
    database_path = tmp_path / "trace-batch.db"
    store = SqliteTraceStore(database_path, settings=_build_settings(database_path))
    started_at = datetime(2026, 6, 24, 23, 0, tzinfo=UTC)

    await store.initialize()
    await store.record_events(
        [
            TraceEvent(
                trace_id="trace_batch_1",
                session_id="session_1",
                event_type="request_received",
                component="api.chat",
                timestamp=started_at,
            ),
            TraceEvent(
                trace_id="trace_batch_1",
                session_id="session_1",
                event_type="response_returned",
                component="api.chat",
                timestamp=started_at + timedelta(seconds=1),
            ),
            TraceEvent(
                trace_id="trace_batch_2",
                session_id="session_2",
                event_type="request_received",
                component="api.health",
                timestamp=started_at + timedelta(seconds=2),
            ),
        ]
    )

    with sqlite3.connect(database_path) as connection:
        run_count = connection.execute("SELECT COUNT(*) FROM trace_runs").fetchone()
        event_rows = connection.execute(
            "SELECT trace_id, sequence_no FROM trace_events ORDER BY trace_id ASC, sequence_no ASC"
        ).fetchall()

    assert run_count == (2,)
    assert event_rows == [
        ("trace_batch_1", 1),
        ("trace_batch_1", 2),
        ("trace_batch_2", 1),
    ]


@pytest.mark.asyncio
async def test_record_events_rolls_back_when_any_event_is_invalid(tmp_path: Path) -> None:
    database_path = tmp_path / "trace-batch-rollback.db"
    store = SqliteTraceStore(database_path, settings=_build_settings(database_path))
    started_at = datetime(2026, 6, 24, 23, 0, tzinfo=UTC)

    await store.initialize()

    with pytest.raises(TraceStoreValidationError, match="event_name"):
        await store.record_events(
            [
                TraceEvent(
                    trace_id="trace_batch_invalid",
                    session_id="session_1",
                    event_type="request_received",
                    component="api.chat",
                    timestamp=started_at,
                ),
                TraceEvent(
                    trace_id="trace_batch_invalid",
                    session_id="session_1",
                    event_type="request_received",
                    event_name="Bad-Event",
                    component="api.chat",
                    timestamp=started_at + timedelta(seconds=1),
                ),
            ]
        )

    with sqlite3.connect(database_path) as connection:
        run_count = connection.execute("SELECT COUNT(*) FROM trace_runs").fetchone()
        event_count = connection.execute("SELECT COUNT(*) FROM trace_events").fetchone()

    assert run_count == (0,)
    assert event_count == (0,)


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