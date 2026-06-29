"""Foundation health composition layered on top of reusable observability checks."""

from __future__ import annotations

from typing import Any

from app.config.view import ApiSettings, get_health_settings, get_observability_settings, get_tooling_settings
from app.contracts.config import ConfigurationView
from app.contracts.health import (
    HEALTH_DEGRADED,
    HEALTH_NOT_CHECKED,
    HEALTH_NOT_CONFIGURED,
    HEALTH_OK,
    HealthStatus,
)
from app.contracts.llm import LLMGateway, LLMHealthResult
from app.contracts.memory import MemoryGateway, MemoryHealthResult
from app.contracts.policy import PolicyService
from app.contracts.tools import ToolGateway
from app.observability.health import HealthAggregator, HealthCheckResult
from app.observability.redaction import Redactor
from app.orchestration.runtime import OrchestrationRuntime
from app.persistence.factory import PersistenceBundle
from app.policy.context import build_readonly_policy_context
from app.policy.health import build_health_policy_request, sanitize_health_payload
from app.persistence.health import (
    build_persistence_health_components,
    evaluate_persistence_bundle,
    evaluate_persistence_component,
)
from app.tools.health import build_tooling_health_check

HealthRegistry = HealthAggregator


def build_foundation_health_registry(
    *,
    config: ConfigurationView,
    config_summary: dict[str, Any],
    redactor: Redactor,
    persistence: PersistenceBundle,
    llm_gateway: LLMGateway,
    memory_gateway: MemoryGateway,
    tool_gateway: ToolGateway,
    orchestrator: OrchestrationRuntime,
) -> HealthRegistry:
    """Build the minimal health registry needed by the foundation app."""

    registry = HealthRegistry(redactor=redactor)
    observability = get_observability_settings(config)
    health_settings = get_health_settings(config)

    registry.register("settings", lambda: HealthCheckResult(status=HEALTH_OK))
    registry.register("config", lambda: _config_result(config_summary))
    registry.register("logging", lambda: HealthCheckResult(status=HEALTH_OK))
    registry.register(
        "policy",
        lambda: _policy_result(policy_service=getattr(orchestrator, "policy_service", None)),
    )
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
    registry.register(
        "mcp",
        lambda: _tooling_result(
            tool_gateway,
            expose_provider_details=health_settings.expose_provider_names,
        ),
    )
    registry.register("llm", lambda: _llm_result(llm_gateway))
    registry.register("orchestration", lambda: _orchestration_result(orchestrator))
    registry.register(
        "persistence",
        lambda: evaluate_persistence_bundle(persistence_checks),
    )
    registry.register("memory", lambda: _memory_result(memory_gateway))
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

    tooling = get_tooling_settings(config)
    llm_profiles = sorted(config.section("llm.profiles").keys())

    summary.update(
        {
            "environment": config.require("app.environment"),
            "active_usecase": config.require("app.active_usecase"),
            "llm_default_profile": _optional_str(config.get("llm.defaults.profile")),
            "llm_profiles": llm_profiles,
            "llm_profiles_count": len(llm_profiles),
            "mcp_configured": bool(tooling.mcp_server.endpoint),
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
        "orchestration": _component_payload(checks, "orchestration"),
        "checks": checks,
    }


async def apply_health_policy(
    *,
    payload: dict[str, Any],
    policy_service: PolicyService,
    config: ConfigurationView,
    trace_id: str | None,
    user_id: str | None,
) -> dict[str, Any]:
    """Filter the API health payload through the phase-5 policy surface."""

    context = build_readonly_policy_context(
        policy_service=policy_service,
        config=config,
        trace_id=trace_id,
        user_id=user_id,
    )
    request = build_health_policy_request(trace_id=trace_id, user_id=user_id, payload=payload)
    decision = await policy_service.evaluate(request, context)
    if decision.is_denied:
        return {"status": payload.get("status", HEALTH_NOT_CHECKED)}

    engine = getattr(policy_service, "engine", None)
    if engine is None:
        return payload
    settings = getattr(engine, "_settings", None)
    if settings is None:
        return payload
    profile_name = settings.default_profile or "default"
    profile = settings.profiles[profile_name]
    return sanitize_health_payload(payload, profile=profile)


async def _policy_result(*, policy_service: PolicyService | None) -> HealthCheckResult:
    if policy_service is None or not hasattr(policy_service, "health"):
        return HealthCheckResult(status=HEALTH_NOT_CONFIGURED, details={"configured": False})

    health = await policy_service.health()
    return HealthCheckResult(
        status=HEALTH_OK if getattr(health, "healthy", False) else HEALTH_DEGRADED,
        details={
            "configured": getattr(health, "configured", True),
            "healthy": getattr(health, "healthy", False),
            "enabled": getattr(health, "enabled", False),
            "mode": getattr(health, "mode", "enforce"),
            "default_profile": getattr(health, "default_profile", "default"),
            "profile_count": getattr(health, "profile_count", 0),
            "rule_count": getattr(health, "rule_count", 0),
            "cache": dict(getattr(health, "cache", {})),
            "audit": dict(getattr(health, "audit", {})),
            "decision_counts": dict(getattr(health, "audit", {}).get("decision_counts", {})),
        },
    )


def _config_result(config_summary: dict[str, Any]) -> HealthCheckResult:
    return HealthCheckResult(status=HEALTH_OK, details=dict(config_summary))


async def _llm_result(llm_gateway: LLMGateway) -> HealthCheckResult:
    health = await llm_gateway.health()
    return HealthCheckResult(
        status=_llm_component_status(health),
        details={
            "providers_configured": health.providers_configured,
            "profiles_configured": health.profiles_configured,
            "default_profile": health.default_profile,
            "providers": {
                name: {
                    "status": summary.status,
                    "type": summary.type,
                    "enabled": summary.enabled,
                }
                for name, summary in health.providers.items()
            },
            "profiles": {
                name: {
                    "status": summary.status,
                    "provider": summary.provider,
                    "enabled": summary.enabled,
                    "supports_streaming": summary.supports_streaming,
                }
                for name, summary in health.profiles.items()
            },
        },
    )


async def _memory_result(memory_gateway: MemoryGateway) -> HealthCheckResult:
    health = await memory_gateway.health()
    normalized = dict(health) if isinstance(health, MemoryHealthResult) else dict(health)
    status = normalized.get("status", HEALTH_NOT_CHECKED)
    return HealthCheckResult(status=status, details=normalized)


async def _tooling_result(
    tool_gateway: ToolGateway,
    *,
    expose_provider_details: bool,
) -> HealthCheckResult:
    health = await tool_gateway.health()
    return build_tooling_health_check(
        health,
        expose_provider_details=expose_provider_details,
    )


async def _orchestration_result(orchestrator: OrchestrationRuntime) -> HealthCheckResult:
    health = await orchestrator.health()
    return HealthCheckResult(
        status=health.status,
        details={
            "enabled": health.enabled,
            "registry_ready": health.registry_ready,
            "default_strategy": health.default_strategy,
            "fallback_strategy": health.fallback_strategy,
            "configured_strategy_count": health.configured_strategy_count,
            "enabled_strategy_count": health.enabled_strategy_count,
            "registered_strategy_count": health.registered_strategy_count,
            "configured_usecase_count": health.configured_usecase_count,
            "enabled_usecase_count": health.enabled_usecase_count,
            "configured_agent_count": health.configured_agent_count,
            "agent_registry_status": health.agent_registry_status,
            "strategies_ready_count": health.metadata.get("strategies_ready_count", 0),
            "strategy_types": health.metadata.get("strategy_types", []),
            "agents": [
                {
                    "agent_name": agent.agent_name,
                    "agent_type": agent.agent_type,
                    "status": agent.status,
                    "enabled": agent.enabled,
                    "configured_llm_profile": agent.configured_llm_profile,
                    "prompt_profile": agent.prompt_profile,
                    "memory_required": agent.memory_required,
                    "tools_required": agent.tools_required,
                    "streaming_supported": agent.streaming_supported,
                    **({"metadata": dict(agent.metadata)} if agent.metadata else {}),
                }
                for agent in health.agents
            ],
            "strategies": [
                {
                    "strategy_name": strategy.strategy_name,
                    "strategy_type": strategy.strategy_type,
                    "status": strategy.status,
                    "enabled": strategy.enabled,
                    "configured_agent": strategy.configured_agent,
                    "configured_llm_profile": strategy.configured_llm_profile,
                    "memory_required": strategy.memory_required,
                    "tools_required": strategy.tools_required,
                    "streaming_supported": strategy.streaming_supported,
                    **({"metadata": dict(strategy.metadata)} if strategy.metadata else {}),
                }
                for strategy in health.strategies
            ],
        },
    )


def _llm_component_status(health: LLMHealthResult) -> HealthStatus:
    if not health.providers_configured or not health.profiles_configured:
        return HEALTH_NOT_CONFIGURED
    if health.status == HEALTH_OK:
        return HEALTH_OK
    if health.status == HEALTH_DEGRADED:
        return HEALTH_DEGRADED
    return HEALTH_DEGRADED


def _has_configured_provider(config: ConfigurationView, path: str) -> bool:
    value = config.get(path)
    return isinstance(value, str) and value.strip() != ""


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _coerce_checks(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def _component_payload(checks: dict[str, Any], name: str) -> dict[str, Any]:
    component = checks.get(name)
    if isinstance(component, dict):
        return dict(component)
    return {"status": HEALTH_NOT_CHECKED}
