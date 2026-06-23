"""Health primitives for the backend foundation phase."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.config.settings import Settings

HealthStatus = Literal["ok", "degraded", "failed", "not_configured", "not_checked"]
HealthCheck = Callable[[], "HealthCheckResult | Awaitable[HealthCheckResult]"]


@dataclass(frozen=True)
class HealthCheckResult:
    """Single health-check outcome."""

    status: HealthStatus
    details: dict[str, Any] = field(default_factory=dict)


class HealthRegistry:
    """Registry that evaluates foundation checks synchronously or asynchronously."""

    def __init__(self) -> None:
        self._checks: dict[str, HealthCheck] = {}

    def register(self, name: str, check: HealthCheck) -> None:
        self._checks[name] = check

    async def evaluate(self) -> dict[str, Any]:
        checks: dict[str, dict[str, Any]] = {}
        overall_status: HealthStatus = "ok"

        for name, check in self._checks.items():
            result = await self._run_check(check)
            check_payload: dict[str, Any] = {"status": result.status}
            check_payload.update(result.details)
            checks[name] = check_payload
            overall_status = _merge_status(overall_status, result.status)

        return {
            "status": overall_status,
            "checks": checks,
        }

    async def _run_check(self, check: HealthCheck) -> HealthCheckResult:
        outcome = check()
        if inspect.isawaitable(outcome):
            return await outcome
        return outcome


def build_foundation_health_registry(
    *,
    settings: Settings,
    raw_config: dict[str, Any],
) -> HealthRegistry:
    """Build the minimal health registry needed by the foundation app."""

    registry = HealthRegistry()

    registry.register("settings", lambda: HealthCheckResult(status="ok"))
    registry.register("config", lambda: _config_result(raw_config))
    registry.register("logging", lambda: HealthCheckResult(status="ok"))
    registry.register("mcp", lambda: _placeholder_result(settings.mcp_main_url is not None))
    registry.register("llm", lambda: _placeholder_result(_llm_configured(settings)))
    registry.register(
        "memory",
        lambda: _placeholder_result(settings.memory_store_config is not None),
    )
    registry.register(
        "workflow_state",
        lambda: _placeholder_result(settings.sqlite_workflow_state_url is not None),
    )
    registry.register(
        "trace",
        lambda: _placeholder_result(settings.sqlite_trace_url is not None),
    )

    return registry


def _config_result(raw_config: dict[str, Any]) -> HealthCheckResult:
    source_path = raw_config.get("source_path")
    if source_path is None:
        return HealthCheckResult(
            status="not_configured",
            details={"configured": False},
        )

    return HealthCheckResult(
        status="ok",
        details={"configured": True},
    )


def _placeholder_result(configured: bool) -> HealthCheckResult:
    return HealthCheckResult(
        status="not_checked",
        details={"configured": configured},
    )


def _llm_configured(settings: Settings) -> bool:
    return any(
        value is not None
        for value in (
            settings.llm_local_qwen_base_url,
            settings.llm_local_qwen_api_key,
            settings.openai_api_key,
            settings.google_api_key,
        )
    )


def _merge_status(current: HealthStatus, new: HealthStatus) -> HealthStatus:
    if current == "failed" or new == "failed":
        return "failed"

    if current == "degraded" or new == "degraded":
        return "degraded"

    if current == "ok" or new == "ok":
        return "ok"

    if current == "not_configured" or new == "not_configured":
        return "not_configured"

    return "not_checked"