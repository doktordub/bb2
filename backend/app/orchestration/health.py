"""Safe orchestration readiness summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.health import build_agent_health_results
from app.agents.models import AgentHealthResult
from app.config.view import AgentsSettings, OrchestrationSettings, StrategySettings, UseCaseSettings
from app.contracts.health import (
    HEALTH_DEGRADED,
    HEALTH_FAILED,
    HEALTH_NOT_CONFIGURED,
    HEALTH_OK,
    HealthStatus,
)
from app.orchestration.models import sanitize_metadata
from app.orchestration.registry import AgentRegistry
from app.orchestration.strategy_registry import StrategyDescriptor, StrategyRegistry

_AGENT_REQUIRED_STRATEGY_TYPES = frozenset({"direct_agent", "retrieval_augmented", "tool_assisted"})
_MEMORY_REQUIRED_STRATEGY_TYPES = frozenset({"retrieval_augmented", "memory_update"})
_TOOL_REQUIRED_STRATEGY_TYPES = frozenset({"tool_assisted"})


@dataclass(frozen=True, slots=True)
class StrategyHealthSummary:
    """Safe readiness summary for one configured strategy."""

    strategy_name: str
    strategy_type: str
    status: HealthStatus
    enabled: bool
    configured_agent: str | None = None
    configured_llm_profile: str | None = None
    memory_required: bool = False
    tools_required: bool = False
    streaming_supported: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OrchestrationHealthResult:
    """Safe readiness summary for the orchestration runtime."""

    status: HealthStatus
    enabled: bool
    registry_ready: bool
    default_strategy: str | None
    fallback_strategy: str | None
    configured_strategy_count: int
    enabled_strategy_count: int
    registered_strategy_count: int
    configured_usecase_count: int
    enabled_usecase_count: int
    configured_agent_count: int
    agent_registry_status: HealthStatus
    agents: tuple[AgentHealthResult, ...] = field(default_factory=tuple)
    strategies: tuple[StrategyHealthSummary, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "agents", tuple(self.agents))
        object.__setattr__(self, "strategies", tuple(self.strategies))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


def build_orchestration_health(
    settings: OrchestrationSettings,
    *,
    strategy_registry: StrategyRegistry,
    agent_registry: AgentRegistry,
    agent_settings: AgentsSettings | None = None,
) -> OrchestrationHealthResult:
    """Build the current orchestration readiness summary without touching external services."""

    registered = strategy_registry.list(enabled_only=False)
    registered_by_name = {descriptor.name: descriptor for descriptor in registered}
    enabled_usecases_by_strategy = _group_enabled_usecases(settings)
    strategy_health = tuple(
        _build_strategy_health(
            orchestration_enabled=settings.enabled,
            strategy_name=name,
            settings=strategy_settings,
            descriptor=registered_by_name.get(name),
            usecases=enabled_usecases_by_strategy.get(name, ()),
        )
        for name, strategy_settings in sorted(settings.strategies.items())
    )
    configured_agents = agent_registry.list()
    enabled_strategy_count = sum(1 for descriptor in strategy_health if descriptor.enabled)
    enabled_usecases = sum(1 for usecase in settings.usecases.values() if usecase.enabled)
    strategy_issues = [
        descriptor
        for descriptor in strategy_health
        if descriptor.enabled and descriptor.status in {HEALTH_DEGRADED, HEALTH_FAILED}
    ]
    agent_health = (
        build_agent_health_results(settings=agent_settings, registry=agent_registry)
        if agent_settings is not None
        else ()
    )
    enabled_agents = tuple(agent for agent in agent_health if agent.enabled)
    agent_failures = tuple(
        agent for agent in enabled_agents if agent.status == HEALTH_FAILED
    )
    registry_ready = settings.enabled and enabled_strategy_count > 0 and not any(
        descriptor.status == HEALTH_FAILED for descriptor in strategy_issues
    )
    agent_required = any(
        descriptor.enabled and bool(descriptor.metadata.get("agent_required", False))
        for descriptor in strategy_health
    )

    if not settings.enabled:
        status = HEALTH_NOT_CONFIGURED
        agent_registry_status = HEALTH_NOT_CONFIGURED
    else:
        if agent_failures:
            agent_registry_status = HEALTH_FAILED if agent_required else HEALTH_DEGRADED
        elif (enabled_agents if agent_health else configured_agents) or not agent_required:
            agent_registry_status = HEALTH_OK
        else:
            agent_registry_status = HEALTH_DEGRADED
        status = (
            HEALTH_OK
            if registry_ready and agent_registry_status == HEALTH_OK and not strategy_issues
            else HEALTH_FAILED
            if agent_registry_status == HEALTH_FAILED
            or any(descriptor.status == HEALTH_FAILED for descriptor in strategy_issues)
            else HEALTH_DEGRADED
        )

    return OrchestrationHealthResult(
        status=status,
        enabled=settings.enabled,
        registry_ready=registry_ready,
        default_strategy=settings.defaults.strategy or None,
        fallback_strategy=settings.defaults.fallback_strategy or None,
        configured_strategy_count=len(settings.strategies),
        enabled_strategy_count=enabled_strategy_count,
        registered_strategy_count=len(registered),
        configured_usecase_count=len(settings.usecases),
        enabled_usecase_count=enabled_usecases,
        configured_agent_count=(
            len(enabled_agents) if agent_health else len(configured_agents)
        ),
        agent_registry_status=agent_registry_status,
        agents=agent_health,
        strategies=strategy_health,
        metadata={
            "strategies_ready_count": sum(1 for descriptor in strategy_health if descriptor.status == HEALTH_OK),
            "strategy_types": sorted(
                {descriptor.strategy_type for descriptor in strategy_health if descriptor.enabled}
            ),
            "registered_agent_count": sum(
                1 for agent in agent_health if bool(agent.metadata.get("registered", False))
            ),
            "streaming_agent_count": sum(
                1 for agent in enabled_agents if agent.streaming_supported
            ),
            "agent_types": sorted({agent.agent_type for agent in enabled_agents}),
        },
    )


def _group_enabled_usecases(settings: OrchestrationSettings) -> dict[str, tuple[UseCaseSettings, ...]]:
    grouped: dict[str, list[UseCaseSettings]] = {}
    for usecase in settings.usecases.values():
        if not usecase.enabled:
            continue
        grouped.setdefault(usecase.strategy, []).append(usecase)
    return {name: tuple(items) for name, items in grouped.items()}


def _build_strategy_health(
    *,
    orchestration_enabled: bool,
    strategy_name: str,
    settings: StrategySettings,
    descriptor: StrategyDescriptor | None,
    usecases: tuple[UseCaseSettings, ...],
) -> StrategyHealthSummary:
    configured_agent = _resolve_configured_agent(settings=settings, descriptor=descriptor, usecases=usecases)
    configured_llm_profile = _resolve_configured_llm_profile(
        settings=settings,
        descriptor=descriptor,
        usecases=usecases,
    )
    memory_required = settings.type in _MEMORY_REQUIRED_STRATEGY_TYPES or settings.memory_enabled or settings.memory_write_enabled
    tools_required = settings.type in _TOOL_REQUIRED_STRATEGY_TYPES or settings.tools_enabled
    agent_required = settings.type in _AGENT_REQUIRED_STRATEGY_TYPES
    issues: list[str] = []

    if not orchestration_enabled:
        status = HEALTH_NOT_CONFIGURED
    elif descriptor is None:
        status = HEALTH_FAILED if settings.enabled else HEALTH_NOT_CONFIGURED
        if settings.enabled:
            issues.append("not_registered")
    elif not settings.enabled or not descriptor.enabled:
        status = HEALTH_NOT_CONFIGURED
    else:
        if agent_required and configured_agent is None:
            issues.append("missing_agent")
        if settings.type == "router" and not settings.candidate_strategies:
            issues.append("missing_candidates")
        if settings.type == "retrieval_augmented" and not memory_required:
            issues.append("memory_disabled")
        if settings.type == "tool_assisted" and not tools_required:
            issues.append("tools_disabled")
        if settings.type == "memory_update" and not settings.memory_write_enabled:
            issues.append("memory_writes_disabled")
        status = HEALTH_DEGRADED if issues else HEALTH_OK

    metadata: dict[str, Any] = {
        "registered": descriptor is not None,
        "allowed_usecase_count": len(settings.allowed_usecases),
        "enabled_usecase_count": len(usecases),
        "agent_required": agent_required,
    }
    if settings.fallback_strategy is not None:
        metadata["fallback_strategy"] = settings.fallback_strategy
    if settings.type == "router":
        metadata["candidate_strategy_count"] = len(settings.candidate_strategies)
    if settings.type == "bounded_planner":
        metadata["max_plan_steps"] = settings.max_plan_steps
        metadata["max_execute_steps"] = settings.max_execute_steps
    if issues:
        metadata["issues"] = issues

    return StrategyHealthSummary(
        strategy_name=strategy_name,
        strategy_type=settings.type,
        status=status,
        enabled=settings.enabled,
        configured_agent=configured_agent,
        configured_llm_profile=configured_llm_profile,
        memory_required=memory_required,
        tools_required=tools_required,
        streaming_supported=descriptor.streaming_supported if descriptor is not None else True,
        metadata=metadata,
    )


def _resolve_configured_agent(
    *,
    settings: StrategySettings,
    descriptor: StrategyDescriptor | None,
    usecases: tuple[UseCaseSettings, ...],
) -> str | None:
    if descriptor is not None and descriptor.default_agent is not None:
        return descriptor.default_agent
    if settings.default_agent is not None:
        return settings.default_agent
    agents = sorted({usecase.agent for usecase in usecases if usecase.agent is not None})
    if len(agents) == 1:
        return agents[0]
    return None


def _resolve_configured_llm_profile(
    *,
    settings: StrategySettings,
    descriptor: StrategyDescriptor | None,
    usecases: tuple[UseCaseSettings, ...],
) -> str | None:
    if descriptor is not None and descriptor.llm_profile is not None:
        return descriptor.llm_profile
    if settings.llm_profile is not None:
        return settings.llm_profile
    profiles = sorted({usecase.llm_profile for usecase in usecases if usecase.llm_profile is not None})
    if len(profiles) == 1:
        return profiles[0]
    return None