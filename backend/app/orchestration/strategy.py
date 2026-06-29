"""Minimal orchestration strategy contract and compatibility re-exports."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from app.contracts.agents import AgentPlugin
from app.contracts.context import OrchestrationContext
from app.contracts.results import OrchestrationResult, StreamEvent
from app.orchestration.events import OrchestrationStreamEvent
from app.orchestration.models import (
    CitationSummary,
    MemorySearchSummary,
    MemoryUpdateSummary,
    OrchestrationStepSummary,
    StrategyPlan,
    StrategyPlanStep,
    ToolCallSummary,
    sanitize_metadata,
)
from app.orchestration.strategies.bounded_planner import BoundedPlannerStrategy
from app.orchestration.strategies.direct_agent import DirectAgentStrategy
from app.orchestration.strategies.echo import EchoStrategy
from app.orchestration.strategies.fallback_answer import FallbackAnswerStrategy
from app.orchestration.strategies.memory_update import MemoryUpdateStrategy
from app.orchestration.strategies.retrieval_augmented import RetrievalAugmentedStrategy
from app.orchestration.strategies.router import RouterStrategy
from app.orchestration.strategies.tool_assisted import ToolAssistedStrategy

StrategyStreamEventType = Literal[
    "response.delta",
    "response.completed",
    "agent.summary",
    "tool.summary",
    "memory.summary",
    "trace.summary",
    "strategy.completed",
    "strategy.error",
    "strategy.cancelled",
]


@dataclass(frozen=True, slots=True)
class StrategyExecutionRequest:
    """Compatibility request wrapper for the deepened strategy boundary."""

    context: OrchestrationContext
    agents: tuple[AgentPlugin, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "agents", tuple(self.agents))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class StrategyExecutionResult:
    """Safe strategy-owned result model ready for runtime/session adaptation."""

    answer: str
    agent_name: str | None = None
    llm_profile: str | None = None
    finish_reason: str = "stop"
    steps: tuple[OrchestrationStepSummary, ...] = field(default_factory=tuple)
    tool_calls: tuple[ToolCallSummary, ...] = field(default_factory=tuple)
    memory_searches: tuple[MemorySearchSummary, ...] = field(default_factory=tuple)
    memory_updates: tuple[MemoryUpdateSummary, ...] = field(default_factory=tuple)
    citations: tuple[CitationSummary, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "answer", _normalize_text(self.answer))
        object.__setattr__(self, "agent_name", _normalize_optional_text(self.agent_name))
        object.__setattr__(self, "llm_profile", _normalize_optional_text(self.llm_profile))
        object.__setattr__(self, "finish_reason", _normalize_text(self.finish_reason))
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        object.__setattr__(self, "memory_searches", tuple(self.memory_searches))
        object.__setattr__(self, "memory_updates", tuple(self.memory_updates))
        object.__setattr__(self, "citations", tuple(self.citations))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))

    def to_legacy_result(
        self,
        *,
        session_id: str,
        trace_id: str,
        strategy_name: str,
    ) -> OrchestrationResult:
        metadata = dict(self.metadata)
        metadata["finish_reason"] = self.finish_reason
        if self.steps:
            metadata["steps"] = [item.as_dict() for item in self.steps]
        if self.memory_searches:
            metadata["memory_searches"] = [item.as_dict() for item in self.memory_searches]
        return OrchestrationResult(
            answer=self.answer,
            session_id=session_id,
            trace_id=trace_id,
            agent_name=self.agent_name,
            strategy_name=strategy_name,
            llm_profile=self.llm_profile,
            tool_calls=[item.as_legacy_dict() for item in self.tool_calls],
            memory_updates=[item.as_legacy_dict() for item in self.memory_updates],
            citations=[item.as_legacy_dict() for item in self.citations],
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class StrategyStreamEvent:
    """Strategy-level event boundary used before runtime stream adaptation."""

    type: StrategyStreamEventType
    text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", _normalize_text(self.type))
        object.__setattr__(self, "text", _normalize_optional_text(self.text))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


class OrchestrationStrategy(Protocol):
    """Runtime strategy contract used by the phase-3 registry and router."""

    name: str

    async def run(
        self,
        *,
        context: OrchestrationContext,
        agents: Sequence[AgentPlugin],
    ) -> OrchestrationResult:
        ...

    def stream(
        self,
        *,
        context: OrchestrationContext,
        agents: Sequence[AgentPlugin],
    ) -> AsyncIterator[StreamEvent | OrchestrationStreamEvent]:
        ...


__all__ = [
    "BoundedPlannerStrategy",
    "DirectAgentStrategy",
    "EchoStrategy",
    "FallbackAnswerStrategy",
    "MemoryUpdateStrategy",
    "OrchestrationStrategy",
    "RetrievalAugmentedStrategy",
    "RouterStrategy",
    "StrategyPlan",
    "StrategyPlanStep",
    "StrategyExecutionRequest",
    "StrategyExecutionResult",
    "StrategyStreamEvent",
    "ToolAssistedStrategy",
]


def _normalize_text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Strategy text values must be strings.")
    normalized = value.strip()
    if not normalized:
        raise ValueError("Strategy text values must not be empty.")
    return normalized


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None