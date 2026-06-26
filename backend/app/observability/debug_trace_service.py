"""Safe trace-store facade for optional local debug routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.contracts.trace import TraceEvent, TraceReadModel, TraceSearchFilters, TraceStore, TraceSummary


class DebugTraceService:
    """Wrap redacted trace-store reads and searches for the API layer."""

    def __init__(
        self,
        *,
        trace_store: TraceStore,
        max_trace_events: int,
        max_search_results: int,
    ) -> None:
        self._trace_store = trace_store
        self._max_trace_events = max_trace_events
        self._max_search_results = max_search_results

    async def read_trace(self, *, trace_id: str, limit: int | None = None) -> dict[str, Any]:
        resolved_limit = _clamp_limit(limit, self._max_trace_events)
        model = await self._trace_store.read_trace(trace_id=trace_id, limit=resolved_limit)
        return {
            "found": model.found,
            "data": {
                "summary": _serialize_summary(model),
                "events": [
                    _serialize_event(event, sequence_no=index + 1)
                    for index, event in enumerate(model.events)
                ],
            },
            "metadata": {
                "limit": resolved_limit,
                "returned_events": len(model.events),
                "total_events": model.event_count,
                "truncated": model.event_count > len(model.events),
            },
        }

    async def search_traces(
        self,
        *,
        status: str | None = None,
        limit: int | None = None,
        errors_only: bool = False,
        usecase: str | None = None,
        event_name: str | None = None,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        resolved_limit = _clamp_limit(limit, self._max_search_results)
        filters = TraceSearchFilters(
            status=_normalize_optional_text(status),
            usecase=_normalize_optional_text(usecase),
            event_name=_normalize_optional_text(event_name),
            event_type=_normalize_optional_text(event_type),
            errors_only=errors_only,
            limit=resolved_limit,
        )
        summaries = await self._trace_store.search_traces(filters=filters)
        return {
            "data": {
                "traces": [_serialize_summary(summary) for summary in summaries],
            },
            "metadata": {
                "limit": resolved_limit,
                "result_count": len(summaries),
            },
        }


def _clamp_limit(value: int | None, maximum: int) -> int:
    if value is None:
        return maximum
    return max(1, min(value, maximum))


def _serialize_summary(summary: TraceSummary | TraceReadModel) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "trace_id": summary.trace_id,
        "status": summary.status,
        "severity": summary.severity,
        "started_at": _format_datetime(summary.started_at),
        "completed_at": _format_datetime(summary.ended_at),
        "last_event_at": _format_datetime(summary.last_event_at),
        "duration_ms": summary.duration_ms,
        "event_count": summary.event_count,
        "error_count": summary.error_count,
        "operation": summary.operation,
        "route_template": summary.route_template,
        "usecase": summary.usecase,
        "event_name": summary.event_name,
        "event_type": summary.event_type,
        "agent_name": summary.agent_name,
        "strategy_name": summary.strategy_name,
        "llm_profile": summary.llm_profile,
        "provider": summary.provider,
        "model": summary.model,
        "tool_name": summary.tool_name,
        "error_type": summary.error_type,
        "error_code": summary.error_code,
        "metadata": dict(summary.metadata),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _serialize_event(event: TraceEvent, *, sequence_no: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sequence_no": sequence_no,
        "event_name": event.resolved_event_name,
        "event_type": event.event_type,
        "created_at": _format_datetime(event.timestamp),
        "component": event.component,
        "status": event.status,
        "severity": event.severity,
        "duration_ms": event.duration_ms,
        "error_type": event.error_type,
        "error_code": event.error_code,
        "payload": dict(event.payload),
    }
    return {key: value for key, value in payload.items() if value is not None}


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized