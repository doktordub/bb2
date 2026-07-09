"""Simple rate limiting primitives for MCP tools and common services."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock
from typing import Protocol

from app.errors import MCPRateLimitError
from app.services.clock import Clock


class RateLimiter(Protocol):
    """Common rate limiter interface."""

    @property
    def mode_name(self) -> str:
        ...

    def check(self, key: str) -> None:
        ...


@dataclass(frozen=True, slots=True)
class DisabledRateLimiter:
    """No-op limiter used when rate limiting is disabled."""

    mode_name: str = "disabled"

    def check(self, key: str) -> None:
        return None


@dataclass(slots=True)
class InMemoryRateLimiter:
    """Deterministic per-key in-memory limiter with a 60 second sliding window."""

    limit_per_minute: int
    clock: Clock
    mode_name: str = field(default="in-memory", init=False)
    _entries: dict[str, deque[datetime]] = field(default_factory=dict, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def check(self, key: str) -> None:
        now = self.clock.now()
        window_start = now - timedelta(minutes=1)

        with self._lock:
            entries = self._entries.setdefault(key, deque())
            while entries and entries[0] <= window_start:
                entries.popleft()

            if len(entries) >= self.limit_per_minute:
                raise MCPRateLimitError(f"Rate limit exceeded for MCP key {key!r}.")

            entries.append(now)