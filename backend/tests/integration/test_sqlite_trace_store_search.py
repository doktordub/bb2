from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contracts.trace import TraceEvent, TraceSearchFilters
from app.persistence.settings import SqliteTraceStoreSettings
from app.persistence.sqlite_trace_store import SqliteTraceStore


@pytest.mark.asyncio
async def test_search_traces_filters_summary_results_without_event_payloads(tmp_path: Path) -> None:
    database_path = tmp_path / "trace-search.db"
    store = SqliteTraceStore(database_path, settings=_build_settings(database_path))
    started_at = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)

    await store.initialize()
    await store.record_events(
        [
            TraceEvent(
                trace_id="trace_ok",
                session_id="session_ok",
                event_type="request",
                event_name="request_received",
                component="api.http",
                timestamp=started_at,
                usecase="support_chat",
                llm_profile="local_reasoning",
                payload={"route_template": "/chat", "operation": "chat"},
            ),
            TraceEvent(
                trace_id="trace_failed",
                session_id="session_failed",
                event_type="tool",
                event_name="tool_call_failed",
                component="tools.documents",
                timestamp=started_at + timedelta(minutes=1),
                status="failed",
                severity="error",
                usecase="support_chat",
                tool_name="documents.search",
                llm_profile="local_reasoning",
                error_type="ToolTimeoutError",
            ),
            TraceEvent(
                trace_id="trace_other",
                session_id="session_other",
                event_type="llm",
                event_name="llm_call_failed",
                component="llm.gateway",
                timestamp=started_at + timedelta(minutes=2),
                status="failed",
                severity="error",
                usecase="research_chat",
                llm_profile="research_reasoning",
                error_type="ProviderError",
            ),
        ]
    )

    failed_tool_results = await store.search_traces(
        filters=TraceSearchFilters(
            status="failed",
            usecase="support_chat",
            event_name="tool_call_failed",
            tool_name="documents.search",
            llm_profile="local_reasoning",
            error_type="ToolTimeoutError",
            limit=10,
        )
    )
    llm_results = await store.search_traces(
        filters=TraceSearchFilters(
            event_type="llm",
            llm_profile="research_reasoning",
            limit=10,
        )
    )

    assert [summary.trace_id for summary in failed_tool_results] == ["trace_failed"]
    assert failed_tool_results[0].event_count == 1
    assert failed_tool_results[0].error_count == 1
    assert failed_tool_results[0].tool_name == "documents.search"
    assert failed_tool_results[0].metadata == {}

    assert [summary.trace_id for summary in llm_results] == ["trace_other"]
    assert llm_results[0].llm_profile == "research_reasoning"


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