"""Safe orchestration capability summaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.orchestration.registry import AgentRegistry
from app.config.view import AgentPluginSettings, AgentsSettings, OrchestrationSettings, StrategySettings, UseCaseSettings
from app.orchestration.models import sanitize_metadata
from app.orchestration.strategy_registry import StrategyDescriptor, StrategyRegistry


@dataclass(frozen=True, slots=True)
class AgentCapabilitySummary:
    """Safe agent descriptor exposed through capabilities."""

    name: str
    display_name: str
    type: str
    streaming_supported: bool
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "display_name", self.display_name.strip())
        object.__setattr__(self, "type", self.type.strip())
        object.__setattr__(self, "capabilities", tuple(self.capabilities))


@dataclass(frozen=True, slots=True)
class OrchestrationUseCaseCapability:
    """Safe use-case summary exposed by orchestration-owned capability reporting."""

    name: str
    display_name: str | None
    description: str | None
    strategy: str
    strategy_type: str
    streaming_supported: bool
    agent: str | None
    llm_profile: str | None
    memory_enabled: bool
    tools_enabled: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OrchestrationCapabilitiesResult:
    """Safe runtime capability surface for orchestration aggregation."""

    enabled: bool
    default_strategy: str | None
    fallback_strategy: str | None
    agents: list[AgentCapabilitySummary] = field(default_factory=list)
    usecases: list[OrchestrationUseCaseCapability] = field(default_factory=list)
    strategies: list[StrategyDescriptor] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "agents", list(self.agents))
        object.__setattr__(self, "usecases", list(self.usecases))
        object.__setattr__(self, "strategies", list(self.strategies))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


def build_orchestration_capabilities(
    settings: OrchestrationSettings,
    *,
    strategy_registry: StrategyRegistry,
    agent_registry: AgentRegistry | None = None,
    agent_settings: AgentsSettings | None = None,
) -> OrchestrationCapabilitiesResult:
    """Build safe orchestration capabilities from validated settings and the runtime registry."""

    strategy_descriptors = strategy_registry.list(enabled_only=False)
    descriptors_by_name = {descriptor.name: descriptor for descriptor in strategy_descriptors}
    agent_descriptors: dict[str, object] = {}
    if agent_registry is not None:
        for descriptor in agent_registry.list():
            name = getattr(descriptor, "name", None)
            if isinstance(name, str) and name.strip():
                agent_descriptors[name] = descriptor
    strategies_by_name = {name: strategy for name, strategy in settings.strategies.items()}
    usecases = [
        _build_usecase_capability(
            usecase,
            descriptor=descriptors_by_name.get(usecase.strategy),
            strategy=strategies_by_name.get(usecase.strategy),
            agent_descriptor=agent_descriptors.get(_resolved_agent_name(usecase, strategies_by_name.get(usecase.strategy))),
        )
        for usecase in settings.usecases.values()
        if usecase.enabled
    ]
    usecases.sort(key=lambda item: item.name)
    agents = build_agent_capability_summaries(
        agent_settings=agent_settings,
        agent_registry=agent_registry,
    )
    return OrchestrationCapabilitiesResult(
        enabled=settings.enabled,
        default_strategy=settings.defaults.strategy or None,
        fallback_strategy=settings.defaults.fallback_strategy or None,
        agents=agents,
        usecases=usecases,
        strategies=strategy_descriptors,
        metadata={
            "registered_strategy_count": len(strategy_descriptors),
            "registered_agent_count": len(agents),
            "strategy_types": sorted(
                {descriptor.type for descriptor in strategy_descriptors if descriptor.enabled}
            ),
        },
    )


def build_agent_capability_summaries(
    *,
    agent_settings: AgentsSettings | None,
    agent_registry: AgentRegistry | None,
) -> list[AgentCapabilitySummary]:
    """Build frontend-safe agent descriptors from config and registry state."""

    descriptors_by_name: dict[str, object] = {}
    if agent_registry is not None:
        for descriptor in agent_registry.list():
            name = getattr(descriptor, "name", None)
            if isinstance(name, str) and name.strip():
                descriptors_by_name[name] = descriptor

    if agent_settings is None:
        return [
            _build_agent_capability_summary(
                name=name,
                descriptor=descriptor,
                configured=None,
            )
            for name, descriptor in sorted(descriptors_by_name.items())
        ]

    summaries: list[AgentCapabilitySummary] = []
    for name, configured in sorted(agent_settings.plugins.items()):
        if not (agent_settings.enabled and configured.enabled):
            continue
        summaries.append(
            _build_agent_capability_summary(
                name=name,
                descriptor=descriptors_by_name.get(name),
                configured=configured,
            )
        )
    return summaries


def _build_agent_capability_summary(
    *,
    name: str,
    descriptor: object | None,
    configured: AgentPluginSettings | None,
) -> AgentCapabilitySummary:
    descriptor_capabilities = None if descriptor is None else getattr(descriptor, "capabilities", None)

    if descriptor_capabilities is not None:
        capabilities = descriptor_capabilities
        display_name = getattr(descriptor, "display_name", None) or _display_name(name)
        agent_type = str(getattr(descriptor, "type", "custom"))
        streaming = bool(getattr(capabilities, "stream", False))
    elif configured is not None:
        capabilities = configured.capabilities
        display_name = configured.display_name or _display_name(name)
        agent_type = str(configured.type)
        streaming = bool(getattr(capabilities, "stream", False))
    else:
        return AgentCapabilitySummary(
            name=name,
            display_name=_display_name(name),
            type="custom",
            streaming_supported=False,
            capabilities=(),
        )

    return AgentCapabilitySummary(
        name=name,
        display_name=display_name,
        type=agent_type,
        streaming_supported=streaming,
        capabilities=_public_capability_labels(capabilities),
    )


def _build_usecase_capability(
    usecase: UseCaseSettings,
    *,
    descriptor: StrategyDescriptor | None,
    strategy: StrategySettings | None,
    agent_descriptor: object | None,
) -> OrchestrationUseCaseCapability:
    strategy_streaming_supported = (
        descriptor.streaming_supported if descriptor is not None else _streaming_supported(strategy)
    )
    agent_streaming_supported = bool(
        getattr(getattr(agent_descriptor, "capabilities", None), "stream", True)
    )
    return OrchestrationUseCaseCapability(
        name=usecase.name,
        display_name=usecase.display_name,
        description=usecase.description,
        strategy=usecase.strategy,
        strategy_type=descriptor.type if descriptor is not None else (usecase.strategy if strategy is None else strategy.type),
        streaming_supported=(strategy_streaming_supported and agent_streaming_supported),
        agent=usecase.agent or (None if strategy is None else strategy.default_agent),
        llm_profile=(
            usecase.llm_profile
            or (None if strategy is None else strategy.llm_profile)
            or getattr(agent_descriptor, "llm_profile", None)
        ),
        memory_enabled=usecase.memory.enabled or bool(strategy and strategy.memory_enabled),
        tools_enabled=usecase.tools.enabled or bool(strategy and strategy.tools_enabled),
        metadata=usecase.metadata,
    )


def _streaming_supported(strategy: StrategySettings | None) -> bool:
    if strategy is None:
        return False
    return strategy.type in {
        "echo",
        "direct_agent",
        "retrieval_augmented",
        "tool_assisted",
        "router",
        "bounded_planner",
        "memory_update",
        "fallback_answer",
    }


def _resolved_agent_name(
    usecase: UseCaseSettings,
    strategy: StrategySettings | None,
) -> str:
    return usecase.agent or ("" if strategy is None else strategy.default_agent or "")


def _display_name(name: str) -> str:
    return name.replace("_", " ").strip().title()


def _public_capability_labels(capabilities: object) -> tuple[str, ...]:
    labels: list[str] = []
    if bool(getattr(capabilities, "answer", False)):
        labels.append("answer")
    if bool(getattr(capabilities, "review", False)):
        labels.append("review")
    if bool(getattr(capabilities, "memory_read", False)) or bool(
        getattr(capabilities, "self_managed_memory", False)
    ):
        labels.append("memory_context")
    if bool(getattr(capabilities, "memory_write", False)):
        labels.append("memory_write")
    if bool(getattr(capabilities, "memory_candidate_extract", False)):
        labels.append("memory_curation")
    if bool(getattr(capabilities, "tool_intents", False)):
        labels.append("tool_reasoning")
    if bool(getattr(capabilities, "tool_execute", False)) or bool(
        getattr(capabilities, "self_managed_tools", False)
    ):
        labels.append("tool_execution")
    return tuple(labels)