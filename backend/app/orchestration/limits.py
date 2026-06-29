"""Lightweight runtime counters and effective limit tracking for orchestration turns."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from app.config.view import OrchestrationSettings, StrategySettings
from app.orchestration.errors import (
    OrchestrationLimitExceededError,
    OrchestrationTimeoutError,
)


@dataclass(slots=True)
class OrchestrationLimitTracker:
    """Track effective limits plus basic runtime counters for one orchestration turn."""

    max_steps: int
    max_tool_calls: int
    max_memory_searches: int
    max_memory_writes: int
    max_llm_calls: int
    max_turn_duration_seconds: int
    max_stream_duration_seconds: int
    steps_used: int = 0
    tool_calls_used: int = 0
    memory_searches_used: int = 0
    memory_writes_used: int = 0
    llm_calls_used: int = 0
    turns_started: int = 0
    streams_started: int = 0
    stream_events_emitted: int = 0
    _turn_started_at: float | None = None
    _stream_started_at: float | None = None

    @classmethod
    def from_settings(
        cls,
        settings: OrchestrationSettings,
        strategy_settings: StrategySettings,
    ) -> "OrchestrationLimitTracker":
        defaults = settings.defaults
        return cls(
            max_steps=_coalesce_limit(strategy_settings.max_steps, defaults.max_steps),
            max_tool_calls=_coalesce_limit(strategy_settings.max_tool_calls, defaults.max_tool_calls),
            max_memory_searches=_coalesce_limit(
                strategy_settings.max_memory_searches,
                defaults.max_memory_searches,
            ),
            max_memory_writes=_coalesce_limit(
                strategy_settings.max_memory_writes,
                defaults.max_memory_writes,
            ),
            max_llm_calls=_coalesce_limit(strategy_settings.max_llm_calls, defaults.max_llm_calls),
            max_turn_duration_seconds=defaults.max_turn_duration_seconds,
            max_stream_duration_seconds=defaults.max_stream_duration_seconds,
        )

    def mark_turn_started(self) -> None:
        self.turns_started += 1
        if self._turn_started_at is None:
            self._turn_started_at = perf_counter()

    def mark_stream_started(self) -> None:
        self.streams_started += 1
        if self._stream_started_at is None:
            self._stream_started_at = perf_counter()

    def mark_stream_event(self) -> None:
        self.check_stream_duration()
        self.stream_events_emitted += 1

    def consume_step(self, *, amount: int = 1) -> None:
        self.check_turn_duration()
        next_value = self.steps_used + amount
        if next_value > self.max_steps:
            raise OrchestrationLimitExceededError(
                f"The request exceeded the configured max step limit ({self.max_steps})."
            )
        self.steps_used = next_value

    def consume_tool_call(self, *, amount: int = 1) -> None:
        self.check_turn_duration()
        next_value = self.tool_calls_used + amount
        if next_value > self.max_tool_calls:
            raise OrchestrationLimitExceededError(
                f"The request exceeded the configured max tool call limit ({self.max_tool_calls})."
            )
        self.tool_calls_used = next_value

    def consume_memory_search(self, *, amount: int = 1) -> None:
        self.check_turn_duration()
        next_value = self.memory_searches_used + amount
        if next_value > self.max_memory_searches:
            raise OrchestrationLimitExceededError(
                (
                    "The request exceeded the configured max memory search limit "
                    f"({self.max_memory_searches})."
                )
            )
        self.memory_searches_used = next_value

    def consume_memory_write(self, *, amount: int = 1) -> None:
        self.check_turn_duration()
        next_value = self.memory_writes_used + amount
        if next_value > self.max_memory_writes:
            raise OrchestrationLimitExceededError(
                (
                    "The request exceeded the configured max memory write limit "
                    f"({self.max_memory_writes})."
                )
            )
        self.memory_writes_used = next_value

    def consume_llm_call(self, *, amount: int = 1) -> None:
        self.check_turn_duration()
        next_value = self.llm_calls_used + amount
        if next_value > self.max_llm_calls:
            raise OrchestrationLimitExceededError(
                f"The request exceeded the configured max LLM call limit ({self.max_llm_calls})."
            )
        self.llm_calls_used = next_value

    def check_turn_duration(self) -> None:
        if self._turn_started_at is None:
            return
        elapsed = perf_counter() - self._turn_started_at
        if elapsed > float(self.max_turn_duration_seconds):
            raise OrchestrationTimeoutError(
                (
                    "The orchestration request exceeded the configured max turn duration "
                    f"({self.max_turn_duration_seconds}s)."
                )
            )

    def check_stream_duration(self) -> None:
        if self._stream_started_at is None:
            return
        elapsed = perf_counter() - self._stream_started_at
        if elapsed > float(self.max_stream_duration_seconds):
            raise OrchestrationTimeoutError(
                (
                    "The orchestration request exceeded the configured max stream duration "
                    f"({self.max_stream_duration_seconds}s)."
                )
            )

    def as_dict(self) -> dict[str, int]:
        return {
            "max_steps": self.max_steps,
            "max_tool_calls": self.max_tool_calls,
            "max_memory_searches": self.max_memory_searches,
            "max_memory_writes": self.max_memory_writes,
            "max_llm_calls": self.max_llm_calls,
            "max_turn_duration_seconds": self.max_turn_duration_seconds,
            "max_stream_duration_seconds": self.max_stream_duration_seconds,
            "steps_used": self.steps_used,
            "tool_calls_used": self.tool_calls_used,
            "memory_searches_used": self.memory_searches_used,
            "memory_writes_used": self.memory_writes_used,
            "llm_calls_used": self.llm_calls_used,
            "turns_started": self.turns_started,
            "streams_started": self.streams_started,
            "stream_events_emitted": self.stream_events_emitted,
        }


def _coalesce_limit(override: int | None, default: int) -> int:
    if isinstance(override, int) and override > 0:
        return override
    return default