"""Safe shaping helpers for memory payloads and context snippets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256
from typing import Any

from app.contracts.memory import MemoryRecord, MemoryResult, MemoryScope


def truncate_text(text: str | None, *, max_chars: int) -> str | None:
    """Bound text to a stable ASCII-safe summary length."""

    if text is None:
        return None

    stripped = text.strip()
    if stripped == "":
        return ""

    if max_chars <= 0 or len(stripped) <= max_chars:
        return stripped
    if max_chars <= 3:
        return stripped[:max_chars]
    return stripped[: max_chars - 3].rstrip() + "..."


def redact_record(
    record: MemoryRecord,
    *,
    include_text: bool = False,
    max_chars: int = 0,
) -> dict[str, Any]:
    """Return a safe record summary without raw text by default."""

    payload: dict[str, Any] = {
        "memory_id": record.memory_id,
        "memory_type": record.memory_type,
        "status": record.status,
        "scope": record.scope.summary(),
        "source_id": record.source_id,
        "document_id": record.document_id,
        "chunk_id": record.chunk_id,
        "tag_count": len(record.tags),
        "metadata": dict(record.metadata),
    }
    if include_text:
        payload["text"] = truncate_text(record.text, max_chars=max_chars)
    return payload


def summarize_result(
    result: MemoryResult,
    *,
    include_text: bool = False,
    max_chars: int = 0,
) -> dict[str, Any]:
    """Return a safe search-hit summary without raw content by default."""

    payload: dict[str, Any] = {
        "memory_id": result.memory_id,
        "memory_type": result.memory_type,
        "score": result.score,
        "source_id": result.source_id,
        "chunk_id": result.chunk_id,
        "metadata": dict(result.metadata),
        "highlight_count": len(result.highlights),
        "related_record_count": len(result.related_records),
    }
    if isinstance(result.record, MemoryRecord):
        payload["record"] = redact_record(
            result.record,
            include_text=include_text,
            max_chars=max_chars,
        )
    elif isinstance(result.record, Mapping):
        payload["record"] = {str(key): value for key, value in result.record.items()}
    if include_text:
        payload["text"] = truncate_text(result.text, max_chars=max_chars)
    return payload


def hash_text(text: str) -> str:
    """Return a stable, trace-safe SHA256 hash label for text content."""

    return f"sha256:{sha256(text.encode('utf-8')).hexdigest()}"


def bound_record(
    record: MemoryRecord,
    *,
    max_chars: int,
) -> MemoryRecord:
    """Return a copy of one memory record with bounded text fields."""

    return replace(
        record,
        text=truncate_text(record.text, max_chars=max_chars) or record.text,
        title=truncate_text(record.title, max_chars=max_chars),
        summary=truncate_text(record.summary, max_chars=max_chars),
    )


def bound_result(
    result: MemoryResult,
    *,
    max_chars: int,
) -> MemoryResult:
    """Return a copy of one search result with bounded text fields."""

    record = result.record
    if not isinstance(record, MemoryRecord):
        record = MemoryRecord(
            memory_id=result.memory_id,
            text=result.text,
            memory_type=result.memory_type or "observation",
            scope=MemoryScope(),
            metadata=dict(result.metadata),
        )
    bounded_record = bound_record(record, max_chars=max_chars)
    return replace(
        result,
        text=truncate_text(result.text, max_chars=max_chars) or result.text,
        highlights=[
            truncate_text(highlight, max_chars=max_chars) or highlight
            for highlight in result.highlights
        ],
        related_records=[
            bound_record(record, max_chars=max_chars) for record in result.related_records
        ],
        record=bounded_record,
    )


def summarize_scores(results: list[MemoryResult]) -> dict[str, float | None]:
    """Return safe score summary values for one bounded search response."""

    scores = [result.score for result in results if isinstance(result.score, (int, float))]
    if not scores:
        return {"max_score": None, "min_score": None}
    return {"max_score": max(scores), "min_score": min(scores)}