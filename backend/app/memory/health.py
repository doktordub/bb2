"""Safe health-shaping helpers for the backend memory runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.contracts.health import HEALTH_NOT_CONFIGURED, HealthStatus
from app.contracts.memory import MemoryHealthResult


def build_unavailable_memory_health(
    *,
    provider: str,
    required: bool,
    reason: str,
    status: HealthStatus = HEALTH_NOT_CONFIGURED,
    enabled: bool = False,
    configured: bool = False,
) -> MemoryHealthResult:
    """Build the safe health payload for disabled or unavailable memory."""

    return MemoryHealthResult(
        status=status,
        enabled=enabled,
        provider=provider,
        configured=configured,
        required=required,
        search_available=False,
        ingest_available=False,
        error=reason,
        metadata={"reason": reason},
    )


def coerce_memory_health_result(
    payload: MemoryHealthResult | Mapping[str, Any],
    *,
    provider: str,
    required: bool,
    enabled: bool = True,
    configured: bool = True,
) -> MemoryHealthResult:
    """Normalize a mapping or existing result into MemoryHealthResult."""

    if isinstance(payload, MemoryHealthResult):
        return payload

    metadata = payload.get("metadata")
    normalized_metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
    return MemoryHealthResult(
        status=_read_optional_str(payload, "status") or HEALTH_NOT_CONFIGURED,
        enabled=_read_bool(payload, "enabled", enabled),
        provider=_read_optional_str(payload, "provider") or provider,
        configured=_read_bool(payload, "configured", configured),
        required=_read_bool(payload, "required", required),
        schema_initialized=_read_optional_bool(payload, "schema_initialized"),
        embedding_model_configured=_read_optional_bool(
            payload,
            "embedding_model_configured",
        ),
        embedding_dimension=_read_optional_int(payload, "embedding_dimension"),
        search_available=_read_optional_bool(payload, "search_available"),
        ingest_available=_read_optional_bool(payload, "ingest_available"),
        error=_read_optional_str(payload, "error") or _read_optional_str(payload, "reason"),
        metadata=normalized_metadata,
    )


def _read_bool(payload: Mapping[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    return default


def _read_optional_bool(payload: Mapping[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    return None


def _read_optional_int(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, int):
        return value
    return None


def _read_optional_str(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None