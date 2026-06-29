"""Deterministic clock fake for session-service tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(slots=True)
class FakeClock:
    """Return configured timestamps in order and record every call."""

    instants: list[datetime]
    fallback: datetime = field(default_factory=lambda: datetime(2026, 1, 1, tzinfo=UTC))
    calls: list[datetime] = field(default_factory=list)

    def now(self) -> datetime:
        if self.instants:
            instant = self.instants.pop(0)
        elif self.calls:
            instant = self.calls[-1]
        else:
            instant = self.fallback

        self.calls.append(instant)
        return instant
