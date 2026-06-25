"""In-memory fake trace store for contract-focused tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.contracts.trace import TraceEvent, TraceReadModel, TraceSearchFilters, TraceSummary


class FakeTraceStore:
    """Deterministic trace fake that records events in memory."""

    def __init__(
        self,
        *,
        record_error: Exception | None = None,
        read_error: Exception | None = None,
        search_error: Exception | None = None,
        health_payload: dict[str, Any] | None = None,
        health_error: Exception | None = None,
    ) -> None:
        self.events: list[TraceEvent] = []
        self._events_by_trace: dict[str, list[TraceEvent]] = {}
        self._record_error = record_error
        self._read_error = read_error
        self._search_error = search_error
        self._health_payload = health_payload or {"status": "ok", "provider": "fake"}
        self._health_error = health_error

    async def record_event(self, event: TraceEvent) -> None:
        if self._record_error is not None:
            raise self._record_error
        self._append_event(event)

    async def record_events(self, events: Sequence[TraceEvent]) -> None:
        if self._record_error is not None:
            raise self._record_error
        for event in events:
            self._append_event(event)

    async def read_trace(
        self,
        *,
        trace_id: str,
        limit: int | None = None,
    ) -> TraceReadModel:
        if self._read_error is not None:
            raise self._read_error
        if limit is not None and limit < 0:
            raise ValueError("Trace read limit must be greater than or equal to 0.")

        trace_events = tuple(self._events_by_trace.get(trace_id, ()))
        if not trace_events:
            return TraceReadModel.not_found(trace_id=trace_id)

        returned_events = trace_events if limit is None else trace_events[:limit]
        return TraceReadModel.from_events(
            trace_id=trace_id,
            events=returned_events,
            total_events=trace_events,
        )

    async def search_traces(self, *, filters: TraceSearchFilters) -> list[TraceSummary]:
        if self._search_error is not None:
            raise self._search_error

        results: list[TraceSummary] = []
        for trace_id, trace_events in self._events_by_trace.items():
            summary = TraceSummary.from_events(trace_id=trace_id, events=trace_events)
            if filters.matches(summary=summary, events=trace_events):
                results.append(summary)

        results.sort(key=_trace_summary_sort_key, reverse=True)
        return results[: filters.limit]

    async def health(self) -> dict[str, Any]:
        if self._health_error is not None:
            raise self._health_error
        return dict(self._health_payload)

    def _append_event(self, event: TraceEvent) -> None:
        self.events.append(event)
        self._events_by_trace.setdefault(event.trace_id, []).append(event)


def _trace_summary_sort_key(summary: TraceSummary) -> tuple[int, str]:
    if summary.started_at is None:
        return (0, "")
    return (1, summary.started_at.isoformat())