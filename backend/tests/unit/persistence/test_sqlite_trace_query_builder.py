from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.contracts.trace import TraceSearchFilters
from app.persistence.sqlite_trace_queries import (
    build_read_trace_events_query,
    build_read_trace_summary_query,
    build_search_trace_summaries_query,
    normalize_trace_read_limit,
)


def test_read_trace_queries_are_parameterized_and_bounded() -> None:
    summary_query = build_read_trace_summary_query(trace_id="trace_123")
    events_query = build_read_trace_events_query(trace_id="trace_123", limit=25)

    assert summary_query.parameters == ("trace_123",)
    assert "WHERE trace_id = ?" in summary_query.sql
    assert events_query.parameters == ("trace_123", 25)
    assert "ORDER BY sequence_no ASC" in events_query.sql
    assert events_query.sql.endswith("LIMIT ?")


def test_search_query_uses_exists_for_event_filters_and_clamps_limit() -> None:
    injected_value = "tool_call_failed' OR 1=1 --"
    filters = TraceSearchFilters(
        started_after=datetime(2026, 6, 24, 23, 0, tzinfo=UTC),
        status="failed",
        session_id_hash="sha256:session_1",
        event_name=injected_value,
        event_type="tool",
        errors_only=True,
        limit=999,
    )

    query = build_search_trace_summaries_query(filters=filters, max_limit=200)

    assert injected_value not in query.sql
    assert query.parameters[:-1] == (
        "2026-06-24T23:00:00+00:00",
        "failed",
        "sha256:session_1",
        injected_value,
        "tool",
    )
    assert query.parameters[-1] == 200
    assert "EXISTS (SELECT 1 FROM trace_events e" in query.sql
    assert "r.error_count > 0" in query.sql


def test_normalize_trace_read_limit_rejects_negative_values() -> None:
    assert normalize_trace_read_limit(None, max_limit=1000) == 1000
    assert normalize_trace_read_limit(1500, max_limit=1000) == 1000
    assert normalize_trace_read_limit(0, max_limit=1000) == 0

    with pytest.raises(ValueError, match="greater than or equal to 0"):
        normalize_trace_read_limit(-1, max_limit=1000)