"""Agent-layer registry ownership and startup composition helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from app.agents.errors import AgentNotFoundError
from app.contracts.config import ConfigurationView
from app.contracts.errors import ConfigurationError

if TYPE_CHECKING:
    from app.config.view import AgentsSettings


class DefaultAgentRegistry:
    """Register, resolve, and summarize configured agent handles."""

    def __init__(self, agents: Mapping[str, object] | None = None) -> None:
        self._agents: dict[str, object] = {}
        for agent in (agents or {}).values():
            self.register(agent)

    @classmethod
    def from_config(cls, config: ConfigurationView) -> DefaultAgentRegistry:
        return build_agent_registry(config)

    def register(self, agent: object) -> None:
        descriptor_getter = getattr(agent, "descriptor", None)
        if not callable(descriptor_getter):
            raise ConfigurationError("Configured agent is missing a safe descriptor.")

        descriptor = cast(Any, descriptor_getter)()
        agent_name = _read_optional_text(getattr(descriptor, "name", None)) or _read_optional_text(
            getattr(agent, "name", None)
        )
        if agent_name is None:
            raise ConfigurationError("Configured agent is missing a valid name.")
        if not bool(getattr(descriptor, "enabled", True)):
            raise ConfigurationError(
                f"Disabled agent '{agent_name}' cannot be registered."
            )
        if agent_name in self._agents:
            raise ConfigurationError(
                f"Duplicate agent registration for '{agent_name}'."
            )
        self._agents[agent_name] = agent

    def resolve(self, agent_name: str) -> object:
        normalized = _read_optional_text(agent_name)
        if normalized is None or normalized not in self._agents:
            raise AgentNotFoundError(
                f"Configured agent '{agent_name}' is not available."
            )
        return self._agents[normalized]

    def require(self, agent_name: str) -> object:
        return self.resolve(agent_name)

    def get(self, agent_name: str) -> object | None:
        normalized = _read_optional_text(agent_name)
        if normalized is None:
            return None
        return self._agents.get(normalized)

    def contains(self, agent_name: str) -> bool:
        normalized = _read_optional_text(agent_name)
        return normalized in self._agents if normalized is not None else False

    def list(self) -> tuple[object, ...]:
        descriptors: list[object] = []
        for _, agent in sorted(self._agents.items()):
            descriptor_getter = getattr(agent, "descriptor", None)
            if callable(descriptor_getter):
                descriptors.append(descriptor_getter())
        return tuple(descriptors)

    @property
    def agents(self) -> dict[str, object]:
        return dict(self._agents)

    def startup_summary(self, *, settings: AgentsSettings | None = None) -> dict[str, object]:
        descriptors = self.list()
        configured_count = len(settings.plugins) if settings is not None else len(descriptors)
        enabled_count = (
            sum(1 for plugin in settings.plugins.values() if plugin.enabled)
            if settings is not None
            else len(descriptors)
        )
        return {
            "enabled": True if settings is None else bool(settings.enabled),
            "configured_count": configured_count,
            "enabled_count": enabled_count,
            "registered_count": len(descriptors),
            "types": sorted(
                {
                    str(agent_type)
                    for descriptor in descriptors
                    if (agent_type := getattr(descriptor, "type", None)) is not None
                }
            ),
            "streaming_supported": any(
                bool(getattr(getattr(descriptor, "capabilities", None), "stream", False))
                for descriptor in descriptors
            ),
            "streaming_agent_count": sum(
                1
                for descriptor in descriptors
                if bool(getattr(getattr(descriptor, "capabilities", None), "stream", False))
            ),
        }


class AgentRegistry(DefaultAgentRegistry):
    """Compatibility concrete registry name for current runtime wiring."""


def build_agent_registry(
    config: ConfigurationView,
    *,
    settings: AgentsSettings | None = None,
) -> AgentRegistry:
    from app.agents.factory import AgentFactory
    from app.config.view import get_agents_settings

    resolved_settings = settings or get_agents_settings(config)
    registry = AgentRegistry()
    if not resolved_settings.enabled:
        return registry

    factory = AgentFactory(settings=resolved_settings)
    for agent_name in sorted(resolved_settings.plugins):
        agent_settings = resolved_settings.plugins[agent_name]
        if not agent_settings.enabled:
            continue
        registry.register(factory.build(agent_settings))
    return registry


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


__all__ = ["AgentRegistry", "DefaultAgentRegistry", "build_agent_registry"]