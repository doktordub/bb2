"""Reusable component health contracts for future backend modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Literal, Protocol, runtime_checkable

HealthStatus = Literal[
    "ok",
    "degraded",
    "failed",
    "not_configured",
    "not_checked",
]
HEALTH_OK: Final[HealthStatus] = "ok"
HEALTH_DEGRADED: Final[HealthStatus] = "degraded"
HEALTH_FAILED: Final[HealthStatus] = "failed"
HEALTH_NOT_CONFIGURED: Final[HealthStatus] = "not_configured"
HEALTH_NOT_CHECKED: Final[HealthStatus] = "not_checked"

HEALTH_STATUSES: tuple[HealthStatus, ...] = (
    HEALTH_OK,
    HEALTH_DEGRADED,
    HEALTH_FAILED,
    HEALTH_NOT_CONFIGURED,
    HEALTH_NOT_CHECKED,
)


@dataclass(slots=True)
class ComponentHealth:
    """Health summary for a single backend component."""

    name: str
    status: HealthStatus
    configured: bool = True
    details: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class HealthCheck(Protocol):
    """Common health-check shape for contract-level components."""

    async def health(self) -> ComponentHealth | dict[str, Any]:
        ...