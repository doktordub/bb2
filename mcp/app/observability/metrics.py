"""Low-cardinality metrics recording helpers for the MCP server."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Mapping, Protocol


ALLOWED_METRIC_TAG_KEYS = frozenset({"tool_name", "capability_name", "status", "error_code"})


class MetricsRecorder(Protocol):
    """Minimal metrics recorder interface used by tool wrappers."""

    @property
    def mode_name(self) -> str:
        ...

    def increment(self, name: str, tags: Mapping[str, object] | None = None) -> None:
        ...

    def timing(self, name: str, value_ms: float, tags: Mapping[str, object] | None = None) -> None:
        ...


@dataclass(frozen=True, slots=True)
class TimingSample:
    """One recorded timing measurement with normalized tags."""

    name: str
    value_ms: float
    tags: dict[str, str]


@dataclass(frozen=True, slots=True)
class NoopMetricsRecorder:
    """Recorder used when metrics emission is disabled."""

    mode_name: str = "noop"

    def increment(self, name: str, tags: Mapping[str, object] | None = None) -> None:
        del name, tags
        return None

    def timing(self, name: str, value_ms: float, tags: Mapping[str, object] | None = None) -> None:
        del name, value_ms, tags
        return None


@dataclass(slots=True)
class InMemoryMetricsRecorder:
    """Thread-safe in-memory metrics recorder used for tests and local diagnostics."""

    mode_name: str = field(default="in-memory", init=False)
    _counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _timings: list[TimingSample] = field(default_factory=list, init=False, repr=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    @property
    def timing_samples(self) -> tuple[TimingSample, ...]:
        with self._lock:
            return tuple(self._timings)

    def increment(self, name: str, tags: Mapping[str, object] | None = None) -> None:
        key = (name, normalize_metric_tags(tags))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1

    def timing(self, name: str, value_ms: float, tags: Mapping[str, object] | None = None) -> None:
        normalized_tags = dict(normalize_metric_tags(tags))
        sample = TimingSample(name=name, value_ms=float(value_ms), tags=normalized_tags)
        with self._lock:
            self._timings.append(sample)

    def counter_value(self, name: str, tags: Mapping[str, object] | None = None) -> int:
        key = (name, normalize_metric_tags(tags))
        with self._lock:
            return self._counters.get(key, 0)


def normalize_metric_tags(tags: Mapping[str, object] | None) -> tuple[tuple[str, str], ...]:
    """Drop unsafe tags and normalize the allowed low-cardinality subset."""

    if not tags:
        return ()

    normalized: dict[str, str] = {}
    for key, value in tags.items():
        if key not in ALLOWED_METRIC_TAG_KEYS:
            continue
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        normalized[key] = text[:64]

    return tuple(sorted(normalized.items()))