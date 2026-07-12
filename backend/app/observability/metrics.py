"""Lightweight metrics interfaces and local implementations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

ALLOWED_METRIC_TAG_KEYS = frozenset(
    {
        "route",
        "method",
        "status_code",
        "component",
        "provider",
        "operation",
        "profile",
        "tool_name",
        "chart_type",
        "renderer",
        "data_source",
        "data_mode",
        "event_type",
        "event_name",
        "success",
        "error_type",
    }
)


class MetricsRecorder(Protocol):
    """Low-cardinality metrics interface for later backend modules."""

    def increment(self, name: str, value: int = 1, tags: dict[str, str] | None = None) -> None:
        ...

    def timing(self, name: str, duration_ms: int, tags: dict[str, str] | None = None) -> None:
        ...


@dataclass(frozen=True, slots=True)
class MetricSample:
    """In-memory metric observation used by tests and local runtime wiring."""

    kind: str
    name: str
    value: int
    tags: dict[str, str]


class NoopMetricsRecorder:
    """Metrics sink used when the feature is disabled."""

    def increment(self, name: str, value: int = 1, tags: dict[str, str] | None = None) -> None:
        return None

    def timing(self, name: str, duration_ms: int, tags: dict[str, str] | None = None) -> None:
        return None


class InMemoryMetricsRecorder:
    """Simple local metrics recorder with tag sanitization."""

    def __init__(self) -> None:
        self._counters: list[MetricSample] = []
        self._timings: list[MetricSample] = []

    def increment(self, name: str, value: int = 1, tags: dict[str, str] | None = None) -> None:
        self._counters.append(
            MetricSample(
                kind="counter",
                name=name,
                value=value,
                tags=sanitize_metric_tags(tags),
            )
        )

    def timing(self, name: str, duration_ms: int, tags: dict[str, str] | None = None) -> None:
        self._timings.append(
            MetricSample(
                kind="timing",
                name=name,
                value=duration_ms,
                tags=sanitize_metric_tags(tags),
            )
        )

    def snapshot(self) -> dict[str, list[MetricSample]]:
        return {
            "counters": list(self._counters),
            "timings": list(self._timings),
        }


def build_metrics_recorder(*, enabled: bool) -> MetricsRecorder:
    """Build the configured metrics recorder without choosing an external backend."""

    if enabled:
        return InMemoryMetricsRecorder()
    return NoopMetricsRecorder()


def sanitize_metric_tags(tags: Mapping[str, object] | None) -> dict[str, str]:
    """Drop unsupported or high-cardinality metric tags."""

    if not tags:
        return {}

    sanitized: dict[str, str] = {}
    for key, value in tags.items():
        normalized_key = str(key).strip()
        if normalized_key not in ALLOWED_METRIC_TAG_KEYS or value is None:
            continue
        sanitized[normalized_key] = str(value)
    return sanitized