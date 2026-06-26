from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.contracts.trace import TraceEvent
from app.persistence.errors import TraceStoreValidationError
from app.persistence.settings import SqliteTraceStoreSettings
from app.persistence.sqlite_trace_store import SqliteTraceStore, _prepare_payload
from app.observability.redaction import REDACTED_VALUE, Redactor


def test_prepare_payload_redacts_sensitive_keys_before_persistence() -> None:
    payload, _, _ = _prepare_payload(
        redactor=Redactor(redact_secrets=True, max_chars=None),
        payload={
            "authorization": "Bearer top-secret",
            "nested": {"api_key": "abc123"},
            "route_template": "/chat",
        },
        max_event_payload_bytes=4096,
        max_error_detail_bytes=1024,
    )

    assert payload["authorization"] == REDACTED_VALUE
    assert payload["nested"] == {"api_key": REDACTED_VALUE}
    assert payload["route_template"] == "/chat"


def test_prepare_event_applies_hash_policy_and_generates_event_id(tmp_path: Path) -> None:
    store = SqliteTraceStore(tmp_path / "trace.db", settings=_build_settings(tmp_path / "trace.db"))
    prepared = store._prepare_event(
        TraceEvent(
            trace_id="trace_12345678",
            session_id="session_123",
            user_id="user_123",
            event_type="request_received",
            component="api.chat",
            timestamp=datetime(2026, 6, 24, 23, 0, tzinfo=UTC),
            payload={"route_template": "/chat"},
        )
    )

    assert prepared.event_id.startswith("evt_")
    assert prepared.session_id is None
    assert prepared.user_id is None
    assert prepared.session_id_hash is not None and prepared.session_id_hash.startswith("sha256:")
    assert prepared.user_id_hash is not None and prepared.user_id_hash.startswith("sha256:")


def test_prepare_event_rejects_invalid_event_name(tmp_path: Path) -> None:
    store = SqliteTraceStore(tmp_path / "trace.db", settings=_build_settings(tmp_path / "trace.db"))

    with pytest.raises(TraceStoreValidationError, match="event_name"):
        store._prepare_event(
            TraceEvent(
                trace_id="trace_12345678",
                session_id="session_123",
                event_type="request_received",
                event_name="Bad-Event",
                component="api.chat",
                timestamp=datetime(2026, 6, 24, 23, 0, tzinfo=UTC),
            )
        )


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