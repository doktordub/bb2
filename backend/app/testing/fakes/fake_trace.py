"""In-memory fake trace store for contract-focused tests."""

from __future__ import annotations

from typing import Any

from app.contracts.trace import TraceEvent


class FakeTraceStore:
    """Deterministic trace fake that records events in memory."""

    def __init__(
        self,
        *,
        record_error: Exception | None = None,
        health_payload: dict[str, Any] | None = None,
        health_error: Exception | None = None,
    ) -> None:
        self.events: list[TraceEvent] = []
        self._record_error = record_error
        self._health_payload = health_payload or {"status": "ok", "provider": "fake"}
        self._health_error = health_error

    async def record_event(self, event: TraceEvent) -> None:
        if self._record_error is not None:
            raise self._record_error
        self.events.append(event)

    async def health(self) -> dict[str, Any]:
        if self._health_error is not None:
            raise self._health_error
        return dict(self._health_payload)