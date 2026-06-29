"""Safe stats-shaping helpers for the backend memory runtime."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.contracts.memory import MemoryRecord, MemoryScope, MemoryStatsResult
from app.memory.scopes import classify_memory_scope, normalize_memory_scope


def build_empty_memory_stats(
    *,
    provider: str | None = None,
    configured: bool = False,
    status: str = "not_configured",
    metadata: Mapping[str, Any] | None = None,
) -> MemoryStatsResult:
    """Build an empty safe stats payload."""

    return MemoryStatsResult(
        total_records=0,
        scope_counts={},
        status_counts={},
        type_counts={},
        status=status,
        provider=provider,
        configured=configured,
        metadata=dict(metadata or {}),
    )


def summarize_records(
    records: Iterable[MemoryRecord],
    *,
    provider: str | None = None,
    configured: bool = True,
    status: str = "ok",
) -> MemoryStatsResult:
    """Summarize in-memory records into the public stats shape."""

    total_records = 0
    scope_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}

    for record in records:
        total_records += 1
        scope_type = classify_memory_scope(record.scope)
        scope_counts[scope_type] = scope_counts.get(scope_type, 0) + 1
        status_counts[record.status] = status_counts.get(record.status, 0) + 1
        type_counts[record.memory_type] = type_counts.get(record.memory_type, 0) + 1

    return MemoryStatsResult(
        total_records=total_records,
        scope_counts=scope_counts,
        status_counts=status_counts,
        type_counts=type_counts,
        status=status,
        provider=provider,
        configured=configured,
    )


def coerce_memory_stats_result(
    payload: MemoryStatsResult | Mapping[str, Any],
    *,
    provider: str | None = None,
    configured: bool = True,
) -> MemoryStatsResult:
    """Normalize a mapping or existing result into MemoryStatsResult."""

    if isinstance(payload, MemoryStatsResult):
        return payload

    total_records = payload.get("total_records")
    scope_counts = payload.get("scope_counts")
    status_counts = payload.get("status_counts")
    type_counts = payload.get("type_counts")
    metadata = payload.get("metadata")
    return MemoryStatsResult(
        total_records=total_records if isinstance(total_records, int) else 0,
        scope_counts=_coerce_int_mapping(scope_counts),
        status_counts=_coerce_int_mapping(status_counts),
        type_counts=_coerce_int_mapping(type_counts),
        status=_read_optional_str(payload, "status") or "ok",
        provider=_read_optional_str(payload, "provider") or provider,
        configured=_read_bool(payload, "configured", configured),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def filter_records_by_scope(
    records: Iterable[MemoryRecord],
    scope: MemoryScope | None,
) -> list[MemoryRecord]:
    """Return records that match the provided scope subset."""

    if scope is None:
        return list(records)

    expected = normalize_memory_scope(scope)
    return [record for record in records if _scope_matches(record.scope, expected)]


def _scope_matches(record_scope: MemoryScope, expected: MemoryScope) -> bool:
    record = normalize_memory_scope(record_scope)
    return all(
        (
            expected.user_id is None or expected.user_id == record.user_id,
            expected.project_id is None or expected.project_id == record.project_id,
            expected.tenant_id is None or expected.tenant_id == record.tenant_id,
            expected.session_id is None or expected.session_id == record.session_id,
            expected.agent_name is None or expected.agent_name == record.agent_name,
            expected.usecase is None or expected.usecase == record.usecase,
            expected.source_id is None or expected.source_id == record.source_id,
            expected.document_id is None or expected.document_id == record.document_id,
            not expected.tags or all(tag in record.tags for tag in expected.tags),
        )
    )


def _coerce_int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        if isinstance(item, int):
            result[str(key)] = item
    return result


def _read_bool(payload: Mapping[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    return default


def _read_optional_str(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None