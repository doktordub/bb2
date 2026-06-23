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
from app.contracts.health import ComponentHealth
from app.contracts.results import AgentResult, OrchestrationResult, StreamEvent


def test_agent_result_defaults() -> None:
    result = AgentResult(answer="hello", agent_name="support")

    assert result.confidence is None
    assert result.llm_profile is None
    assert result.tool_calls == []
    assert result.memory_updates == []
    assert result.handoff_to is None
    assert result.citations == []
    assert result.metadata == {}


def test_agent_result_collections_are_not_shared() -> None:
    first = AgentResult(answer="hello", agent_name="support")
    second = AgentResult(answer="hi", agent_name="router")

    first.tool_calls.append({"tool": "search"})
    first.memory_updates.append({"memory_id": "mem_1"})
    first.citations.append({"source": "doc"})
    first.metadata["key"] = "value"

    assert second.tool_calls == []
    assert second.memory_updates == []
    assert second.citations == []
    assert second.metadata == {}


def test_orchestration_result_defaults() -> None:
    result = OrchestrationResult(answer="hello", session_id="session_1")

    assert result.trace_id is None
    assert result.agent_name is None
    assert result.strategy_name is None
    assert result.llm_profile is None
    assert result.tool_calls == []
    assert result.memory_updates == []
    assert result.citations == []
    assert result.metadata == {}


def test_stream_event_defaults() -> None:
    event = StreamEvent(event_type="message_started")

    assert event.data == {}


def test_component_health_defaults() -> None:
    health = ComponentHealth(name="llm", status="unknown")

    assert health.configured is True
    assert health.details == {}


def test_error_hierarchy() -> None:
    assert issubclass(ConfigurationError, BackendError)
    assert issubclass(PolicyDeniedError, BackendError)
    assert issubclass(GatewayError, BackendError)
    assert issubclass(LLMGatewayError, GatewayError)
    assert issubclass(ToolGatewayError, GatewayError)
    assert issubclass(MemoryGatewayError, GatewayError)
    assert issubclass(WorkflowStateError, GatewayError)
    assert issubclass(TraceStoreError, GatewayError)