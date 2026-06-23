"""Foundation health composition layered on top of reusable observability checks."""

from __future__ import annotations

from typing import Any

from app.config.view import get_observability_settings
from app.contracts.config import ConfigurationView
from app.contracts.health import (
    HEALTH_NOT_CHECKED,
    HEALTH_OK,
)
from app.contracts.trace import TraceStore
from app.observability.health import HealthAggregator, HealthCheckResult
from app.observability.redaction import Redactor

HealthRegistry = HealthAggregator


def build_foundation_health_registry(
    *,
    config: ConfigurationView,
    config_summary: dict[str, Any],
    redactor: Redactor,
    trace_store: TraceStore,
) -> HealthRegistry:
    """Build the minimal health registry needed by the foundation app."""

    registry = HealthRegistry(redactor=redactor)
    observability = get_observability_settings(config)

    registry.register("settings", lambda: HealthCheckResult(status=HEALTH_OK))
    registry.register("config", lambda: _config_result(config_summary))
    registry.register("logging", lambda: HealthCheckResult(status=HEALTH_OK))
    registry.register(
        "observability",
        lambda: HealthCheckResult(
            status=HEALTH_OK,
            details={
                "trace_enabled": observability.trace_enabled,
                "trace_payloads_enabled": observability.trace_payloads_enabled,
                "trace_store_required": observability.trace_store_required,
                "structured_logging": observability.structured_logging,
                "metrics_enabled": observability.metrics_enabled,
                "trace_store_configured": _has_configured_provider(
                    config,
                    "persistence.trace.provider",
                ),
            },
        ),
    )
    registry.register("mcp", lambda: _placeholder_result(bool(config.get("mcp.main.url"))))
    registry.register("llm", lambda: _placeholder_result(bool(config.section("llm.profiles"))))
    registry.register(
        "memory",
        lambda: _placeholder_result(_has_configured_provider(config, "persistence.memory.provider")),
    )
    registry.register(
        "workflow_state",
        lambda: _placeholder_result(
            _has_configured_provider(config, "persistence.workflow_state.provider")
        ),
    )
    registry.register(
        "trace",
        trace_store,
    )

    return registry


def build_safe_config_summary(config: ConfigurationView) -> dict[str, Any]:
    """Build a reusable secret-safe summary for logs and health responses."""

    summary: dict[str, Any] = {"configured": True}
    if not bool(config.get("health.expose_config_summary", True)):
        return summary

    summary.update(
        {
            "environment": config.require("app.environment"),
            "active_usecase": config.require("app.active_usecase"),
            "llm_profiles_count": len(config.section("llm.profiles")),
            "mcp_configured": bool(config.get("mcp.main.url")),
        }
    )

    if bool(config.get("health.expose_provider_names", True)):
        summary.update(
            {
                "llm_providers": sorted(config.section("llm.providers").keys()),
                "workflow_state_provider": config.require("persistence.workflow_state.provider"),
                "trace_provider": config.require("persistence.trace.provider"),
                "memory_provider": config.require("persistence.memory.provider"),
            }
        )

    return summary


def _config_result(config_summary: dict[str, Any]) -> HealthCheckResult:
    return HealthCheckResult(status=HEALTH_OK, details=dict(config_summary))


def _placeholder_result(configured: bool) -> HealthCheckResult:
    return HealthCheckResult(
        status=HEALTH_NOT_CHECKED,
        details={"configured": configured},
    )


def _has_configured_provider(config: ConfigurationView, path: str) -> bool:
    value = config.get(path)
    return isinstance(value, str) and value.strip() != ""
