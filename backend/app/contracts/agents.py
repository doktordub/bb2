"""Agent plugin contracts for orchestration-managed execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
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


class AgentPlugin(Protocol):
    """Provider-neutral agent interface used by strategies."""

    name: str
    description: str
    capabilities: list[str]

    async def run(self, context: OrchestrationContext) -> AgentResult:
        ...