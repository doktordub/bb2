"""Foundation health composition layered on top of reusable observability checks."""

from __future__ import annotations

from typing import Any

from app.config.view import ApiSettings
from app.config.view import get_observability_settings
from app.contracts.config import ConfigurationView
from app.contracts.health import (
    HEALTH_NOT_CHECKED,
    HEALTH_OK,
)
from app.observability.health import HealthAggregator, HealthCheckResult
from app.observability.redaction import Redactor
from app.persistence.factory import PersistenceBundle
from app.persistence.health import (
    build_persistence_health_components,
    evaluate_persistence_bundle,
    evaluate_persistence_component,
)

HealthRegistry = HealthAggregator


def build_foundation_health_registry(
    *,
    config: ConfigurationView,
    config_summary: dict[str, Any],
    redactor: Redactor,
    persistence: PersistenceBundle,
) -> HealthRegistry:
    """Build the minimal health registry needed by the foundation app."""

    registry = HealthRegistry(redactor=redactor)
    observability = get_observability_settings(config)

    registry.register("settings", lambda: HealthCheckResult(status=HEALTH_OK))
    registry.register("config", lambda: _config_result(config_summary))
    registry.register("logging", lambda: HealthCheckResult(status=HEALTH_OK))
    persistence_checks = build_persistence_health_components(persistence)
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
        "persistence",
        lambda: evaluate_persistence_bundle(persistence_checks),
    )
    registry.register(
        "memory",
        lambda: evaluate_persistence_component(persistence_checks["memory"]),
    )
    registry.register(
        "workflow_state",
        lambda: evaluate_persistence_component(persistence_checks["workflow_state"]),
    )
    registry.register(
        "trace",
        lambda: evaluate_persistence_component(persistence_checks["trace"]),
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


def build_api_health_payload(
    *,
    health_payload: dict[str, Any],
    service_name: str,
    version: str,
    environment: str,
    trace_id: str | None,
    api_settings: ApiSettings | None,
    streaming_enabled: bool,
) -> dict[str, Any]:
    """Map composed foundation health data to the API-facing shape."""

    checks = dict(_coerce_checks(health_payload.get("checks")))
    return {
        "status": health_payload.get("status", HEALTH_NOT_CHECKED),
        "trace_id": trace_id,
        "service": service_name,
        "version": version,
        "environment": environment,
        "backend": {
            "configured": True,
            "service": service_name,
            "version": version,
            "environment": environment,
        },
        "api": {
            "configured": bool(api_settings is not None and api_settings.enabled),
            "docs_enabled": bool(api_settings is not None and api_settings.docs_enabled),
            "streaming_enabled": streaming_enabled,
        },
        "workflow_state": _component_payload(checks, "workflow_state"),
        "trace": _component_payload(checks, "trace"),
        "memory": _component_payload(checks, "memory"),
        "llm": _component_payload(checks, "llm"),
        "mcp": _component_payload(checks, "mcp"),
        "checks": checks,
    }


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


def _coerce_checks(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def _component_payload(checks: dict[str, Any], name: str) -> dict[str, Any]:
    component = checks.get(name)
    if isinstance(component, dict):
        return dict(component)
    return {"status": HEALTH_NOT_CHECKED}
