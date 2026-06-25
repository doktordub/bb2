"""Persistence health helpers with required-versus-optional semantics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.contracts.health import (
    HEALTH_DEGRADED,
    HEALTH_FAILED,
    HEALTH_NOT_CONFIGURED,
    HEALTH_OK,
    HealthStatus,
)
from app.observability.health import HealthCheckResult
from app.persistence.factory import PersistenceBundle


class SupportsHealth(Protocol):
    async def health(self) -> dict[str, Any]:
        ...


@dataclass(frozen=True, slots=True)
class PersistenceHealthComponent:
    """Persistence component plus its startup requirement policy."""

    name: str
    provider: str
    required: bool
    component: SupportsHealth


def build_persistence_health_components(
    bundle: PersistenceBundle,
) -> dict[str, PersistenceHealthComponent]:
    """Create health-check descriptors for the persistence bundle."""

    return {
        "workflow_state": PersistenceHealthComponent(
            name="workflow_state",
            provider=bundle.settings.workflow_state.provider,
            required=True,
            component=bundle.workflow_state,
        ),
        "trace": PersistenceHealthComponent(
            name="trace",
            provider=bundle.settings.trace.provider,
            required=bundle.settings.trace.required,
            component=bundle.trace_store,
        ),
        "memory": PersistenceHealthComponent(
            name="memory",
            provider=bundle.settings.memory.provider,
            required=bundle.settings.memory.required,
            component=bundle.memory,
        ),
    }


async def evaluate_persistence_component(
    component: PersistenceHealthComponent,
) -> HealthCheckResult:
    """Evaluate one persistence component with required-store semantics."""

    try:
        payload = await component.component.health()
    except Exception as exc:
        return HealthCheckResult(
            status=HEALTH_FAILED if component.required else HEALTH_DEGRADED,
            details={
                "configured": True,
                "provider": component.provider,
                "required": component.required,
                "error_type": type(exc).__name__,
            },
        )

    normalized = _normalize_component_payload(payload, component=component)
    return HealthCheckResult(
        status=_effective_component_status(
            _coerce_health_status(normalized.get("status")),
            required=component.required,
        ),
        details=normalized,
    )


async def evaluate_persistence_bundle(
    components: Mapping[str, PersistenceHealthComponent],
) -> HealthCheckResult:
    """Evaluate aggregate persistence readiness for `/health`."""

    statuses: dict[str, HealthStatus] = {}
    overall = HEALTH_OK

    for name, component in components.items():
        result = await evaluate_persistence_component(component)
        statuses[name] = result.status
        overall = _merge_persistence_status(
            overall,
            result.status,
            required=component.required,
        )

    return HealthCheckResult(
        status=overall,
        details={
            "configured": True,
            "required_components": sum(1 for component in components.values() if component.required),
            "optional_components": sum(1 for component in components.values() if not component.required),
            "components": statuses,
        },
    )


def _normalize_component_payload(
    payload: dict[str, Any],
    *,
    component: PersistenceHealthComponent,
) -> dict[str, Any]:
    normalized = dict(payload)
    normalized["configured"] = bool(normalized.get("configured", True))
    normalized["provider"] = str(normalized.get("provider", component.provider))
    normalized["required"] = bool(normalized.get("required", component.required))
    normalized["status"] = _coerce_health_status(normalized.get("status"))
    return normalized


def _coerce_health_status(value: Any) -> HealthStatus:
    if value == HEALTH_OK:
        return HEALTH_OK
    if value == HEALTH_DEGRADED:
        return HEALTH_DEGRADED
    if value == HEALTH_FAILED:
        return HEALTH_FAILED
    if value == HEALTH_NOT_CONFIGURED:
        return HEALTH_NOT_CONFIGURED
    return HEALTH_NOT_CONFIGURED


def _effective_component_status(status: HealthStatus, *, required: bool) -> HealthStatus:
    if required and status == HEALTH_NOT_CONFIGURED:
        return HEALTH_FAILED
    if not required and status == HEALTH_FAILED:
        return HEALTH_DEGRADED
    return status


def _merge_persistence_status(
    current: HealthStatus,
    new: HealthStatus,
    *,
    required: bool,
) -> HealthStatus:
    if current == HEALTH_FAILED:
        return HEALTH_FAILED

    if required and new == HEALTH_FAILED:
        return HEALTH_FAILED

    if new == HEALTH_DEGRADED:
        return HEALTH_DEGRADED

    if not required and new == HEALTH_FAILED:
        return HEALTH_DEGRADED

    return current