"""Clock abstraction for deterministic runtime services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Time source abstraction used by common services."""

    def now(self) -> datetime:
        ...


@dataclass(frozen=True, slots=True)
class SystemClock:
    """Production clock implementation backed by UTC wall clock time."""

    def now(self) -> datetime:
        return datetime.now(UTC)