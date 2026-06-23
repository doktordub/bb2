"""Trace-store construction boundary for backend runtime wiring."""

from __future__ import annotations

from pathlib import Path

from app.config.settings import BACKEND_ROOT
from app.contracts.config import ConfigurationView
from app.contracts.errors import ConfigurationError
from app.contracts.trace import TraceStore
from app.persistence.sqlite_trace_store import SqliteTraceStore


async def build_trace_store(config: ConfigurationView) -> TraceStore:
    """Build and initialize the configured trace-store implementation."""

    provider = _read_trace_provider(config)
    if provider != "sqlite":
        raise ConfigurationError(f"Unsupported trace store provider: {provider}")

    store = SqliteTraceStore(resolve_trace_store_path(config))
    await store.initialize()
    return store


def resolve_trace_store_path(config: ConfigurationView) -> Path:
    """Resolve the SQLite trace path relative to the backend project root."""

    configured_path = config.get("persistence.trace.path")
    if isinstance(configured_path, str) and configured_path.strip():
        candidate = Path(configured_path)
    else:
        candidate = Path(str(config.require("app.data_dir"))) / "trace.db"

    if not candidate.is_absolute():
        candidate = BACKEND_ROOT / candidate

    return candidate.resolve(strict=False)


def _read_trace_provider(config: ConfigurationView) -> str:
    provider = config.get("persistence.trace.provider")
    if not isinstance(provider, str) or provider.strip() == "":
        raise ConfigurationError("Missing persistence.trace.provider")
    return provider.strip().lower()