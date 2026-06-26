from __future__ import annotations

from pathlib import Path

import pytest

from app.persistence.settings import SqliteTraceStoreSettings
from app.persistence.sqlite_trace_store import SqliteTraceStore


@pytest.mark.asyncio
async def test_sqlite_trace_store_health_returns_safe_readiness_details(tmp_path: Path) -> None:
    database_path = tmp_path / "trace-health.db"
    store = SqliteTraceStore(database_path, settings=_build_settings(database_path))

    await store.initialize()

    health = await store.health()

    assert health == {
        "status": "ok",
        "configured": True,
        "provider": "sqlite",
        "required": True,
        "database_exists": True,
        "journal_mode": "wal",
        "synchronous": "normal",
        "retention_enabled": False,
        "schema_initialized": True,
        "schema_version": 2,
    }


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