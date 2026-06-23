"""Shared request and orchestration context contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.contracts.config import ConfigurationView
    from app.contracts.llm import LLMGateway
    from app.contracts.memory import MemoryGateway
    from app.contracts.policy import PolicyService
    from app.contracts.state import WorkflowStateStore
    from app.contracts.tools import ToolGateway
    from app.contracts.trace import TraceStore


@dataclass(slots=True)
class RequestContext:
    """Normalized request object after API and session resolution."""

    user_id: str
    session_id: str
    message: str
    usecase: str | None = None
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrchestrationContext:
    """Capability container passed into strategies and agents."""

    request: RequestContext
    llm: LLMGateway
    memory: MemoryGateway
    state: WorkflowStateStore
    tools: ToolGateway
    trace: TraceStore
    policy: PolicyService
    config: ConfigurationView
    runtime_metadata: dict[str, Any]