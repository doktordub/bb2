"""Shared request and orchestration context contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.config.view import OrchestrationSettings, StrategySettings
    from app.contracts.config import ConfigurationView
    from app.contracts.llm import LLMGateway
    from app.contracts.memory import MemoryGateway
    from app.contracts.policy import PolicyService
    from app.contracts.tools import ToolGateway
    from app.contracts.trace import TraceStore
    from app.observability.tracing import TraceRecorder
    from app.orchestration.limits import OrchestrationLimitTracker
    from app.orchestration.models import OrchestrationRuntimeContext
    from app.orchestration.state_delta import WorkflowStateSnapshot


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
    state: WorkflowStateSnapshot | None
    tools: ToolGateway
    trace: TraceStore
    policy: PolicyService
    config: ConfigurationView
    runtime_metadata: dict[str, Any] = field(default_factory=dict)
    runtime: OrchestrationRuntimeContext | None = None
    settings: OrchestrationSettings | None = None
    strategy_settings: StrategySettings | None = None
    observability: TraceRecorder | None = None
    limits: OrchestrationLimitTracker | None = None
    metadata: dict[str, Any] = field(default_factory=dict)