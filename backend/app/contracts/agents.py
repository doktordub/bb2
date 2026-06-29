"""Compatibility agent contracts bridging orchestration and the new agent layer."""

from __future__ import annotations

from importlib import import_module
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.agents.base import AgentHandle, LegacyCompatibleAgent
    from app.agents.models import (
        AgentCapabilities,
        AgentDescriptor,
        AgentHealthResult,
        AgentReviewResult,
        AgentRunRequest,
        AgentRunResult,
        AgentStreamEvent,
        AgentTask,
        AgentType,
        AgentUsageSummary,
        AgentWarning,
    )
    from app.agents.result_builder import (
        build_run_request_from_context,
        from_legacy_agent_result,
        to_legacy_agent_result,
    )
    from app.contracts.context import OrchestrationContext
    from app.contracts.results import AgentResult


@dataclass(slots=True)
class AgentMetadata:
    """Static metadata describing an agent plugin."""

    name: str
    description: str
    capabilities: list[str]
    enabled: bool = True
    default_llm_profile: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_descriptor(self) -> "AgentDescriptor":
        """Convert the legacy metadata surface into a safe structured descriptor."""

        from app.agents.models import AgentCapabilities, AgentDescriptor

        capabilities = AgentCapabilities(
            answer=True,
            stream=True,
            tool_intents=bool(self.allowed_tools),
        )
        return AgentDescriptor(
            name=self.name,
            type="custom",
            display_name=self.name.replace("_", " ").title(),
            description=self.description,
            enabled=self.enabled,
            llm_profile=self.default_llm_profile,
            capabilities=capabilities,
            metadata={
                **self.metadata,
                "allowed_tools": tuple(self.allowed_tools),
                "legacy_capabilities": tuple(self.capabilities),
            },
        )


class AgentPlugin(Protocol):
    """Provider-neutral agent interface used by strategies."""

    name: str
    description: str
    capabilities: list[str]

    async def run(self, context: OrchestrationContext) -> AgentResult:
        ...


_LAZY_EXPORTS = {
    "AgentCapabilities": ("app.agents.models", "AgentCapabilities"),
    "AgentDescriptor": ("app.agents.models", "AgentDescriptor"),
    "AgentHandle": ("app.agents.base", "AgentHandle"),
    "AgentHealthResult": ("app.agents.models", "AgentHealthResult"),
    "AgentReviewResult": ("app.agents.models", "AgentReviewResult"),
    "AgentRunRequest": ("app.agents.models", "AgentRunRequest"),
    "AgentRunResult": ("app.agents.models", "AgentRunResult"),
    "AgentStreamEvent": ("app.agents.models", "AgentStreamEvent"),
    "AgentTask": ("app.agents.models", "AgentTask"),
    "AgentType": ("app.agents.models", "AgentType"),
    "AgentUsageSummary": ("app.agents.models", "AgentUsageSummary"),
    "AgentWarning": ("app.agents.models", "AgentWarning"),
    "LegacyCompatibleAgent": ("app.agents.base", "LegacyCompatibleAgent"),
    "build_run_request_from_context": (
        "app.agents.result_builder",
        "build_run_request_from_context",
    ),
    "from_legacy_agent_result": ("app.agents.result_builder", "from_legacy_agent_result"),
    "to_legacy_agent_result": ("app.agents.result_builder", "to_legacy_agent_result"),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EXPORTS:
        raise AttributeError(name)
    module_name, attribute_name = _LAZY_EXPORTS[name]
    module = import_module(module_name)
    return getattr(module, attribute_name)


__all__ = [
    "AgentCapabilities",
    "AgentDescriptor",
    "AgentHandle",
    "AgentHealthResult",
    "AgentMetadata",
    "AgentPlugin",
    "AgentReviewResult",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentStreamEvent",
    "AgentTask",
    "AgentType",
    "AgentUsageSummary",
    "AgentWarning",
    "LegacyCompatibleAgent",
    "build_run_request_from_context",
    "from_legacy_agent_result",
    "to_legacy_agent_result",
]