"""Compatibility wrapper re-exporting the agent-layer registry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol, cast

from app.contracts.agents import AgentPlugin
from app.contracts.config import ConfigurationView

if TYPE_CHECKING:
    from app.config.view import AgentsSettings


class _StructuredRegistryProtocol(Protocol):
    def register(self, agent: object) -> None: ...
    def resolve(self, agent_name: str) -> object: ...
    def require(self, agent_name: str) -> object: ...
    def get(self, agent_name: str) -> object | None: ...
    def contains(self, agent_name: str) -> bool: ...
    def list(self) -> tuple[object, ...]: ...
    def startup_summary(self, *, settings: AgentsSettings | None = None) -> dict[str, object]: ...

    @property
    def agents(self) -> dict[str, object]: ...


class AgentRegistry:
    """Thin compatibility wrapper around the agent-layer registry."""

    def __init__(self, agents: Mapping[str, AgentPlugin] | None = None) -> None:
        self._registry: _StructuredRegistryProtocol
        self._registry = _build_structured_registry(agents=agents)

    @classmethod
    def from_config(cls, config: ConfigurationView) -> AgentRegistry:
        instance = cls()
        from app.agents.registry import build_agent_registry

        instance._registry = build_agent_registry(config)
        return instance

    def register(self, agent: AgentPlugin) -> None:
        self._registry.register(cast(Any, agent))

    def resolve(self, agent_name: str) -> AgentPlugin:
        return cast(AgentPlugin, self._registry.resolve(agent_name))

    def require(self, agent_name: str) -> AgentPlugin:
        return cast(AgentPlugin, self._registry.require(agent_name))

    def get(self, agent_name: str) -> AgentPlugin | None:
        agent = self._registry.get(agent_name)
        return None if agent is None else cast(AgentPlugin, agent)

    def contains(self, agent_name: str) -> bool:
        return self._registry.contains(agent_name)

    def list(self) -> tuple[object, ...]:
        return self._registry.list()

    def startup_summary(self, *, settings: AgentsSettings | None = None) -> dict[str, object]:
        return self._registry.startup_summary(settings=settings)

    @property
    def agents(self) -> dict[str, AgentPlugin]:
        return cast(dict[str, AgentPlugin], self._registry.agents)


def load_configured_agents(config: ConfigurationView) -> dict[str, AgentPlugin]:
    return AgentRegistry.from_config(config).agents


def agent_component(agent: AgentPlugin, agent_name: str) -> str:
    component = getattr(agent, "component", None)
    if isinstance(component, str) and component.strip():
        return component.strip()
    return f"agent.{agent_name.strip()}"


def _build_structured_registry(
    *,
    agents: Mapping[str, AgentPlugin] | None = None,
) -> _StructuredRegistryProtocol:
    from app.agents.registry import AgentRegistry as StructuredAgentRegistry

    return cast(_StructuredRegistryProtocol, StructuredAgentRegistry(agents=agents))


__all__ = ["AgentRegistry", "agent_component", "load_configured_agents"]