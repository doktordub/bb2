from __future__ import annotations

from app.contracts.context import RequestContext
from app.contracts.results import OrchestrationResult as LegacyOrchestrationResult
from app.orchestration.context import build_orchestration_request, build_runtime_context
from app.orchestration.models import OrchestrationStepSummary, ToolCallSummary
from app.orchestration.result_builder import (
    build_orchestration_result,
    orchestration_result_from_contract,
    orchestration_result_to_contract,
)
from app.orchestration.state_delta import WorkflowStateDelta, workflow_state_snapshot_from_document


def test_builders_create_safe_orchestration_request_and_runtime_context() -> None:
    request = RequestContext(
        user_id="local_user",
        session_id="session_123",
        message="hello",
        usecase="default_chat",
        trace_id="trace_123",
        metadata={
            "request_id": "request_123",
            "client_host": "127.0.0.1",
            "authorization": "secret",
            "headers_safe": {"x-trace-id": "trace_123"},
        },
    )
    snapshot = workflow_state_snapshot_from_document(
        session_id="session_123",
        state={
            "version": 3,
            "conversation": {
                "messages": [
                    {"role": "user", "content": "hello"},
                ]
            },
            "workflow": {"pending_actions": []},
            "last_result": {"agent_name": "support_agent"},
            "metadata": {"usecase": "default_chat"},
        },
    )

    orchestration_request = build_orchestration_request(request=request, state=snapshot)
    runtime_context = build_runtime_context(request)

    assert orchestration_request.trace_id == "trace_123"
    assert orchestration_request.workflow_state == snapshot
    assert "authorization" not in orchestration_request.metadata
    assert orchestration_request.metadata["headers_safe"] == {"x-trace-id": "trace_123"}

    assert runtime_context.request_id == "request_123"
    assert runtime_context.client == "127.0.0.1"
    assert "authorization" not in runtime_context.metadata


def test_orchestration_result_builders_sanitize_summaries_and_round_trip_to_legacy() -> None:
    result = build_orchestration_result(
        answer="answer",
        session_id="session_123",
        trace_id="trace_123",
        usecase="default_chat",
        strategy_name="direct_agent",
        agent_name="support_agent",
        llm_profile="fake_profile",
        steps=[
            OrchestrationStepSummary(
                step_id="step_1",
                step_type="llm",
                status="completed",
                metadata={"provider_payload": {"choices": []}, "safe": True},
            )
        ],
        tool_calls=[
            ToolCallSummary(
                tool_name="search_docs",
                status="completed",
                safe_message="2 docs found",
                metadata={"raw_payload": {"id": 1}, "latency_ms": 10},
            )
        ],
        metadata={"secret_token": "hidden", "usecase": "should_not_override"},
        state_delta=WorkflowStateDelta(metadata_patch={"last_turn": "ok"}),
    )

    legacy = orchestration_result_to_contract(result)
    rebuilt = orchestration_result_from_contract(legacy, usecase="default_chat")

    assert result.steps[0].metadata == {"safe": True}
    assert result.tool_calls[0].metadata == {"latency_ms": 10}
    assert "secret_token" not in result.metadata
    assert legacy.metadata["usecase"] == "default_chat"
    assert legacy.metadata["state_delta"]["metadata_patch"] == {"last_turn": "ok"}
    assert rebuilt.strategy_name == "direct_agent"
    assert rebuilt.tool_calls[0].tool_name == "search_docs"


def test_orchestration_result_from_legacy_uses_safe_defaults() -> None:
    legacy = LegacyOrchestrationResult(
        answer="Echo: hello",
        session_id="session_123",
        trace_id="trace_123",
        agent_name="support_agent",
        strategy_name="direct_agent",
        llm_profile="fake_profile",
        tool_calls=[{"tool_name": "search_docs", "status": "completed"}],
        memory_updates=[{"operation": "remember", "status": "completed"}],
        citations=[{"source": "kb://doc-1"}],
        metadata={"provider_payload": {"raw": True}},
    )

    result = orchestration_result_from_contract(legacy, usecase="default_chat")

    assert result.usecase == "default_chat"
    assert result.tool_calls[0].tool_name == "search_docs"
    assert result.memory_updates[0].operation == "remember"
    assert result.citations[0].source == "kb://doc-1"
    assert result.metadata == {}