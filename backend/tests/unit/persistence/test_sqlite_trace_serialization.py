from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.persistence.sqlite_trace_store import _prepare_payload
from app.observability.redaction import Redactor


@dataclass(frozen=True, slots=True)
class ExamplePayload:
    title: str
    created_at: datetime


def test_prepare_payload_keeps_json_safe_runtime_values() -> None:
    payload, payload_json, payload_size = _prepare_payload(
        redactor=Redactor(redact_secrets=True, max_chars=None),
        payload={
            "bytes": b"hello",
            "record": ExamplePayload(
                title="demo",
                created_at=datetime(2026, 6, 24, 12, 0, tzinfo=UTC),
            ),
        },
        max_event_payload_bytes=4096,
        max_error_detail_bytes=1024,
    )

    assert payload == {
        "bytes": "hello",
        "record": {
            "title": "demo",
            "created_at": "2026-06-24T12:00:00+00:00",
        },
    }
    assert payload_json == '{"bytes":"hello","record":{"title":"demo","created_at":"2026-06-24T12:00:00+00:00"}}'
    assert payload_size == len(payload_json.encode("utf-8"))


def test_prepare_payload_truncates_oversized_error_detail_and_payload() -> None:
    payload, payload_json, payload_size = _prepare_payload(
        redactor=Redactor(redact_secrets=True, max_chars=None),
        payload={
            "details": "x" * 400,
            "small_value": "ok",
        },
        max_event_payload_bytes=512,
        max_error_detail_bytes=80,
    )

    assert payload["details"] == {
        "truncated": True,
        "original_size_bytes": 402,
        "max_size_bytes": 80,
    }
    assert payload["small_value"] == "ok"
    assert payload_size <= 512


def test_prepare_payload_replaces_oversized_payload_with_bounded_summary() -> None:
    payload, payload_json, payload_size = _prepare_payload(
        redactor=Redactor(redact_secrets=True, max_chars=None),
        payload={
            "details": "x" * 400,
            "large_value": "y" * 400,
        },
        max_event_payload_bytes=120,
        max_error_detail_bytes=80,
    )

    assert payload["truncated"] is True
    assert sorted(payload.get("retained_keys", [])) == ["details", "large_value"] or payload == {"truncated": True}
    assert payload_size <= 120
    assert payload_json.startswith('{"truncated":true')