"""Shared backend contract models for the contract-first backend slice."""

from app.contracts.agents import AgentMetadata, AgentPlugin
from app.contracts.config import ConfigurationLoader, ConfigurationView
from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.errors import (
    BackendError,
    ConfigurationError,
    GatewayError,
    LLMGatewayError,
    MemoryGatewayError,
    PolicyDeniedError,
    ToolGatewayError,
    TraceStoreError,
    WorkflowStateError,
)
from app.contracts.health import ComponentHealth, HealthCheck, HealthStatus
from app.contracts.llm import (
    LLMGateway,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMRole,
    LLMStreamDelta,
    LLMUsage,
)
from app.contracts.memory import (
    MemoryGateway,
    MemoryRecord,
    MemoryResult,
    MemoryScope,
    MemorySearchRequest,
    MemoryWrite,
)
from app.contracts.policy import PolicyAction, PolicyDecision, PolicyRequest, PolicyService
from app.contracts.results import (
    AgentResult,
    OrchestrationResult,
    StreamEvent,
    StreamEventType,
)
from app.contracts.state import (
    DEFAULT_WORKFLOW_STATE_VERSION,
    WORKFLOW_STATE_RESET_MODE_DELETE_STATE_ROW,
    WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE,
    WORKFLOW_STATE_RESET_MODES,
    WorkflowStateRecord,
    WorkflowStateResetMode,
    WorkflowStateStore,
    default_workflow_state,
)
from app.contracts.strategies import OrchestrationStrategy, StrategyMetadata
from app.contracts.tools import ToolCallRequest, ToolGateway, ToolResult, ToolSpec
from app.contracts.trace import TraceEvent, TraceStore

__all__ = [
    "AgentMetadata",
    "AgentResult",
    "AgentPlugin",
    "BackendError",
    "ComponentHealth",
    "ConfigurationLoader",
    "ConfigurationError",
    "ConfigurationView",
    "GatewayError",
    "HealthCheck",
    "HealthStatus",
    "LLMGateway",
    "LLMGatewayError",
    "LLMMessage",
    "LLMRequest",
    "LLMResponse",
    "LLMRole",
    "LLMStreamDelta",
    "LLMUsage",
    "MemoryGateway",
    "MemoryGatewayError",
    "MemoryRecord",
    "MemoryResult",
    "MemoryScope",
    "MemorySearchRequest",
    "MemoryWrite",
    "OrchestrationContext",
    "OrchestrationResult",
    "OrchestrationStrategy",
    "PolicyAction",
    "PolicyDecision",
    "PolicyDeniedError",
    "PolicyRequest",
    "PolicyService",
    "RequestContext",
    "StreamEvent",
    "StreamEventType",
    "StrategyMetadata",
    "ToolCallRequest",
    "ToolGateway",
    "ToolGatewayError",
    "ToolResult",
    "ToolSpec",
    "TraceEvent",
    "TraceStore",
    "TraceStoreError",
    "WorkflowStateResetMode",
    "WorkflowStateRecord",
    "WorkflowStateStore",
    "WorkflowStateError",
    "WORKFLOW_STATE_RESET_MODE_DELETE_STATE_ROW",
    "WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE",
    "WORKFLOW_STATE_RESET_MODES",
    "DEFAULT_WORKFLOW_STATE_VERSION",
    "default_workflow_state",
]