"""Strategy contracts for orchestration flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.contracts.agents import AgentPlugin
    from app.contracts.context import OrchestrationContext
    from app.contracts.results import OrchestrationResult


@dataclass(slots=True)
class StrategyMetadata:
    """Static metadata describing an orchestration strategy."""

    name: str
    description: str
    supports_streaming: bool = False
    default_llm_profile: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class OrchestrationStrategy(Protocol):
    """Provider-neutral orchestration strategy interface."""

    name: str

    async def run(
        self,
        context: OrchestrationContext,
        agents: list[AgentPlugin],
    ) -> OrchestrationResult:
        ...