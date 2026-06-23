"""Policy service contracts for gateway and runtime operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from app.contracts.context import OrchestrationContext

PolicyAction = Literal[
    "llm.complete",
    "llm.stream",
    "memory.search",
    "memory.upsert",
    "memory.forget",
    "tool.list",
    "tool.call",
    "state.load",
    "state.save",
    "state.reset",
]


@dataclass(slots=True)
class PolicyRequest:
    """Normalized policy evaluation request."""

    action: PolicyAction
    component: str
    resource: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyDecision:
    """Result of evaluating whether an action is allowed."""

    allowed: bool
    reason: str | None = None
    requires_approval: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class PolicyService(Protocol):
    """Policy contract used to gate orchestration actions."""

    async def evaluate(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> PolicyDecision:
        ...

    async def require_allowed(
        self,
        request: PolicyRequest,
        context: OrchestrationContext,
    ) -> None:
        ...