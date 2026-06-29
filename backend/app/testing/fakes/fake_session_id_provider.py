"""Deterministic session ID provider for unit and integration tests."""

from __future__ import annotations

from collections.abc import Iterable


class FakeSessionIdProvider:
    """Generate deterministic session identifiers for tests."""

    def __init__(
        self,
        ids: Iterable[str] | None = None,
        *,
        prefix: str = "session",
    ) -> None:
        self._queued_ids = list(ids or [])
        self._prefix = prefix
        self._counter = 0

    def new_session_id(self) -> str:
        if self._queued_ids:
            return self._queued_ids.pop(0)

        self._counter += 1
        return f"{self._prefix}_{self._counter:04d}"