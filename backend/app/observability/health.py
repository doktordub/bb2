"""Reusable health aggregation for backend observability."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.contracts.health import (
    ComponentHealth,
    HEALTH_DEGRADED,
    HEALTH_FAILED,
    HEALTH_NOT_CHECKED,
    HEALTH_NOT_CONFIGURED,
    HEALTH_OK,
    HealthCheck,
    HealthStatus,
)
from app.observability.redaction import Redactor


@dataclass(frozen=True)
class HealthCheckResult:
    """Simple status-plus-details shape for composed health checks."""

    status: HealthStatus
    details: dict[str, Any] = field(default_factory=dict)


HealthCheckValue = ComponentHealth | HealthCheckResult | Mapping[str, Any]
HealthCheckRegistration = HealthCheck | Callable[[], HealthCheckValue | Awaitable[HealthCheckValue]]


class HealthAggregator:
    """Evaluate component checks without letting one bad check crash `/health`."""

    def __init__(self, *, redactor: Redactor) -> None:
        self._redactor = redactor
        self._checks: dict[str, HealthCheckRegistration] = {}

    def register(self, name: str, check: HealthCheckRegistration) -> None:
        self._checks[name] = check

    async def evaluate(self, *, include_details: bool = True) -> dict[str, Any]:
        checks: dict[str, dict[str, Any]] = {}
        overall_status: HealthStatus = HEALTH_OK

        for name, check in self._checks.items():
            normalized = await self._evaluate_check(name, check)
            safe_payload = self._redact_check_payload(normalized, include_details=include_details)
            checks[name] = safe_payload
            overall_status = _merge_status(
                overall_status,
                _coerce_status(safe_payload.get("status")),
            )

        return {
            "status": overall_status,
            "checks": checks,
        }

    async def _evaluate_check(
        self,
        name: str,
        check: HealthCheckRegistration,
    ) -> dict[str, Any]:
        try:
            result = await self._run_check(check)
        except Exception as exc:
            return {
                "status": HEALTH_FAILED,
                "error_type": type(exc).__name__,
                "component": name,
            }

        return _normalize_health_result(result)

    async def _run_check(self, check: HealthCheckRegistration) -> HealthCheckValue:
        outcome: HealthCheckValue | Awaitable[HealthCheckValue]
        if isinstance(check, HealthCheck):
            outcome = check.health()
        else:
            outcome = check()

        if inspect.isawaitable(outcome):
            return await outcome

        return outcome

    def _redact_check_payload(
        self,
        payload: dict[str, Any],
        *,
        include_details: bool,
    ) -> dict[str, Any]:
        redacted = self._redactor.redact(payload)
        if not isinstance(redacted, dict):
            return {"status": HEALTH_FAILED}

        status = _coerce_status(redacted.get("status"))
        if not include_details:
            return {"status": status}

        safe_payload: dict[str, Any] = {"status": status}
        for key, value in redacted.items():
            if key != "status":
                safe_payload[str(key)] = value
        return safe_payload


def _normalize_health_result(result: HealthCheckValue) -> dict[str, Any]:
    if isinstance(result, HealthCheckResult):
        payload: dict[str, Any] = {"status": result.status}
        payload.update(result.details)
        return payload

    if isinstance(result, ComponentHealth):
        payload = {
            "status": result.status,
            "configured": result.configured,
        }
        payload.update(result.details)
        return payload

    payload = {"status": _coerce_status(result.get("status"))}
    for key, value in result.items():
        if key != "status":
            payload[str(key)] = value
    return payload


def _coerce_status(value: Any) -> HealthStatus:
    if value == HEALTH_OK:
        return HEALTH_OK
    if value == HEALTH_DEGRADED:
        return HEALTH_DEGRADED
    if value == HEALTH_FAILED:
        return HEALTH_FAILED
    if value == HEALTH_NOT_CONFIGURED:
        return HEALTH_NOT_CONFIGURED
    if value == HEALTH_NOT_CHECKED:
        return HEALTH_NOT_CHECKED
    return HEALTH_NOT_CHECKED


def _merge_status(current: HealthStatus, new: HealthStatus) -> HealthStatus:
    if current == HEALTH_FAILED or new == HEALTH_FAILED:
        return HEALTH_FAILED

    if current == HEALTH_DEGRADED or new == HEALTH_DEGRADED:
        return HEALTH_DEGRADED

    if current == HEALTH_OK or new == HEALTH_OK:
        return HEALTH_OK

    if current == HEALTH_NOT_CONFIGURED or new == HEALTH_NOT_CONFIGURED:
        return HEALTH_NOT_CONFIGURED

    return HEALTH_NOT_CHECKED