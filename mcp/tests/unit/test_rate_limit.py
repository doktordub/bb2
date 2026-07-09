from datetime import UTC, datetime, timedelta

import pytest

from app.errors import MCPRateLimitError
from app.services.rate_limit import DisabledRateLimiter, InMemoryRateLimiter


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def test_disabled_rate_limiter_is_noop() -> None:
    limiter = DisabledRateLimiter()

    limiter.check("tool.call")


def test_in_memory_rate_limiter_blocks_after_limit_until_window_expires() -> None:
    clock = FrozenClock(datetime(2026, 7, 8, tzinfo=UTC))
    limiter = InMemoryRateLimiter(limit_per_minute=2, clock=clock)

    limiter.check("tool.call")
    limiter.check("tool.call")

    with pytest.raises(MCPRateLimitError):
        limiter.check("tool.call")

    clock.advance(timedelta(seconds=61))
    limiter.check("tool.call")