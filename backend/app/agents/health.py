"""Safe agent health and startup summaries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.contracts.health import HEALTH_FAILED, HEALTH_NOT_CONFIGURED, HEALTH_OK

if TYPE_CHECKING:
    from app.agents.models import AgentHealthResult
    from app.config.view import AgentPluginSettings, AgentsSettings
    from app.orchestration.registry import AgentRegistry


def build_agent_health_results(
    *,
    settings: "AgentsSettings",
    registry: "AgentRegistry",
) -> tuple["AgentHealthResult", ...]:
    """Build a safe readiness summary for configured agents."""

    descriptors_by_name: dict[str, object] = {}
    for descriptor in registry.list():
        name = _read_optional_text(getattr(descriptor, "name", None))
        if name is not None:
            descriptors_by_name[name] = descriptor
    return tuple(
        _build_agent_health_result(
            settings=settings,
            plugin=plugin,
            descriptor=descriptors_by_name.get(name),
        )
        for name, plugin in sorted(settings.plugins.items())
    )


def build_agent_startup_summary(
    *,
    settings: "AgentsSettings",
    registry: "AgentRegistry",
) -> dict[str, object]:
    """Build the redacted agent summary emitted during startup."""

    from app.agents.trace_helpers import build_health_trace_summary

    health_results = build_agent_health_results(settings=settings, registry=registry)
    registered_agents = [
        health
        for health in health_results
        if bool(health.metadata.get("registered", False))
    ]
    failed_registrations = [
        health.agent_name
        for health in health_results
        if health.enabled and health.status == HEALTH_FAILED
    ]
    return {
        "enabled": settings.enabled,
        "configured_count": len(settings.plugins),
        "enabled_count": sum(1 for health in health_results if health.enabled),
        "registered_count": len(registered_agents),
        "types": sorted({health.agent_type for health in registered_agents}),
        "streaming_supported": any(
            health.streaming_supported for health in registered_agents
        ),
        "streaming_agent_count": sum(
            1 for health in registered_agents if health.streaming_supported
        ),
        "registered_agents": [
            build_health_trace_summary(health) for health in registered_agents
        ],
        **(
            {"registration_failures": failed_registrations}
            if failed_registrations
            else {}
        ),
    }


def _build_agent_health_result(
    *,
    settings: "AgentsSettings",
    plugin: "AgentPluginSettings",
    descriptor: object | None,
) -> "AgentHealthResult":
    from app.agents.capabilities import capabilities_from_settings, memory_required, tools_required
    from app.agents.models import AgentHealthResult

    effective_enabled = settings.enabled and plugin.enabled
    configured_capabilities = capabilities_from_settings(plugin.capabilities)
    resolved_capabilities = (
        getattr(descriptor, "capabilities", configured_capabilities)
        if descriptor is not None
        else configured_capabilities
    )
    resolved_type = (
        str(getattr(descriptor, "type", plugin.type))
        if descriptor is not None
        else str(plugin.type)
    )
    resolved_llm_profile = plugin.llm_profile
    if resolved_llm_profile is None and descriptor is not None:
        resolved_llm_profile = _read_optional_text(getattr(descriptor, "llm_profile", None))

    if not effective_enabled:
        status = HEALTH_NOT_CONFIGURED
    elif descriptor is None:
        status = HEALTH_FAILED
    else:
        status = HEALTH_OK if bool(getattr(descriptor, "enabled", True)) else HEALTH_NOT_CONFIGURED

    metadata: dict[str, Any] = {"registered": descriptor is not None}
    return AgentHealthResult(
        agent_name=plugin.name,
        agent_type=resolved_type,
        status=status,
        enabled=effective_enabled,
        configured_llm_profile=resolved_llm_profile,
        prompt_profile=plugin.prompt_profile,
        memory_required=memory_required(resolved_capabilities),
        tools_required=tools_required(resolved_capabilities),
        streaming_supported=bool(getattr(resolved_capabilities, "stream", False)),
        metadata=metadata,
    )


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


__all__ = ["build_agent_health_results", "build_agent_startup_summary"]