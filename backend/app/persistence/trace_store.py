"""Trace-store construction boundary for backend runtime wiring."""

from __future__ import annotations

from pathlib import Path

from app.contracts.config import ConfigurationView
from app.contracts.errors import ConfigurationError
from app.contracts.trace import TraceStore
from app.persistence.settings import get_persistence_settings
from app.persistence.sqlite_trace_store import SqliteTraceStore


async def build_trace_store(config: ConfigurationView) -> TraceStore:
    """Build and initialize the configured trace-store implementation."""

    trace_settings = get_persistence_settings(config).trace
    if trace_settings.provider != "sqlite" or trace_settings.sqlite is None:
        raise ConfigurationError(
            f"Unsupported trace store provider: {trace_settings.provider}"
        )

    store = SqliteTraceStore(trace_settings.sqlite.path, settings=trace_settings.sqlite)
    await store.initialize()
    return store


def resolve_trace_store_path(config: ConfigurationView) -> Path:
    """Resolve the SQLite trace path relative to the backend project root."""

    trace_settings = get_persistence_settings(config).trace
    if trace_settings.sqlite is None:
        raise ConfigurationError(
            f"Trace store provider does not expose a SQLite path: {trace_settings.provider}"
        )
    return trace_settings.sqlite.path