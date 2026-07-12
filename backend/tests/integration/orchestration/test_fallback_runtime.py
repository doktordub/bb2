from __future__ import annotations

from typing import cast

import pytest

from app.agents.errors import AgentPolicyDeniedError
from app.contracts.errors import LLMGatewayError
from app.contracts.state import default_workflow_state
from app.orchestration.models import OrchestrationRequest, OrchestrationRuntimeContext
from app.orchestration.runtime import DefaultOrchestrationRuntime
from app.orchestration.state_delta import workflow_state_snapshot_from_document
from app.policy.service import DefaultPolicyService
from app.testing.fakes import (
    FakeAgent,
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeTraceStore,
    FakeWorkflowStateStore,
)


def build_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "app": {"active_usecase": "default_chat"},
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "direct_agent",
                    "fallback_strategy": "fallback_answer",
                    "max_steps": 8,
                    "max_tool_calls": 4,
                    "max_memory_searches": 3,
                    "max_llm_calls": 6,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                },
                "strategies": {
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["default_chat"],
                        "llm_profile": "fake_chat",
                    },
                    "fallback_answer": {
                        "enabled": True,
                        "type": "fallback_answer",
                        "allowed_usecases": ["default_chat"],
                        "llm_profile": "fallback_profile",
                        "message": "Fallback static message.",
                    },
                },
                "usecases": {
                    "default_chat": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "allowed_strategies": ["direct_agent", "fallback_answer"],
                        "policy_profile": "default",
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "llm_profile": "fake_chat",
                }
            },
            "llm": {"defaults": {"profile": "fake_chat"}},
            "observability": {
                "trace_enabled": True,
                "trace_payloads_enabled": True,
                "trace_store_required": True,
                "redact_secrets": True,
                "max_trace_payload_chars": 8000,
            },
        }
    )


def build_request() -> tuple[OrchestrationRequest, OrchestrationRuntimeContext]:
    session_id = "session_fallback_runtime"
    trace_id = "trace_fallback_runtime"
    return (
        OrchestrationRequest(
            session_id=session_id,
            trace_id=trace_id,
            user_id="user_1",
            message="Need a safe answer",
            usecase="default_chat",
            metadata={"request_id": "request_fallback_runtime"},
            workflow_state=workflow_state_snapshot_from_document(
                session_id=session_id,
                state=default_workflow_state(session_id),
            ),
        ),
        OrchestrationRuntimeContext(
            request_id="request_fallback_runtime",
            trace_id=trace_id,
            session_id=session_id,
            user_id="user_1",
        ),
    )


def build_runtime(trace_store: FakeTraceStore) -> DefaultOrchestrationRuntime:
    runtime = DefaultOrchestrationRuntime.from_config(
        config=build_config(),
        llm_gateway=FakeLLMGateway(response_text="Safe fallback answer"),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=trace_store,
        policy_service=FakePolicyService(),
    )
    agent = cast(FakeAgent, runtime.agent_registry.require("support_agent"))

    async def fail_run(*, request: object, context: object) -> object:
        _ = request
        _ = context
        raise LLMGatewayError("primary strategy failed")

    async def fail_stream(*, request: object, context: object):
        _ = request
        _ = context
        raise LLMGatewayError("primary strategy failed")
        yield None

    agent.run = fail_run  # type: ignore[method-assign]
    agent.stream = fail_stream  # type: ignore[method-assign]
    return runtime


@pytest.mark.asyncio
async def test_runtime_returns_fallback_answer_for_degradable_primary_failure() -> None:
    trace_store = FakeTraceStore()
    runtime = build_runtime(trace_store)
    request, context = build_request()

    result = await runtime.run_turn(request=request, context=context)

    assert result.answer == "Safe fallback answer"
    assert result.strategy_name == "fallback_answer"
    assert result.metadata["fallback_used"] is True
    assert result.metadata["failed_strategy"] == "direct_agent"
    assert result.metadata["failed_error_code"] == "dependency_unavailable"
    assert result.state_delta is not None
    assert result.state_delta.metadata_patch["fallback_used"] is True
    assert result.state_delta.metadata_patch["failed_strategy"] == "direct_agent"
    assert [event.resolved_event_name for event in trace_store.events] == [
        "orchestration_started",
        "strategy_selected",
        "strategy_selected",
        "strategy_fallback_used",
        "orchestration_completed",
    ]


@pytest.mark.asyncio
async def test_runtime_stream_turn_emits_fallback_events_after_degradable_primary_failure() -> None:
    runtime = build_runtime(FakeTraceStore())
    request, context = build_request()

    events = [event async for event in runtime.stream_turn(request=request, context=context)]

    assert [event.type for event in events] == [
        "orchestration.started",
        "strategy.selected",
        "strategy.selected",
        "response.delta",
        "orchestration.completed",
        "response.completed",
    ]
    assert events[2].metadata["fallback_used"] is True
    assert events[3].text == "Safe fallback answer"
    assert events[4].result is not None
    assert events[4].result.metadata["fallback_used"] is True


@pytest.mark.asyncio
async def test_runtime_fallback_succeeds_with_real_policy_service() -> None:
    trace_store = FakeTraceStore()
    config = build_config()
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=FakeLLMGateway(response_text="Safe fallback answer"),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=trace_store,
        policy_service=DefaultPolicyService(config),
    )
    agent = cast(FakeAgent, runtime.agent_registry.require("support_agent"))

    async def fail_run(*, request: object, context: object) -> object:
        _ = request
        _ = context
        raise LLMGatewayError("primary strategy failed")

    agent.run = fail_run  # type: ignore[method-assign]

    request, context = build_request()

    result = await runtime.run_turn(request=request, context=context)

    assert result.strategy_name == "fallback_answer"
    assert result.answer == "Fallback static message."
    assert result.metadata["fallback_used"] is True
    assert result.metadata["failed_error_code"] == "dependency_unavailable"


@pytest.mark.asyncio
async def test_runtime_returns_explicit_policy_block_answer_for_policy_like_agent_failures() -> None:
    trace_store = FakeTraceStore()
    runtime = build_runtime(trace_store)
    agent = cast(FakeAgent, runtime.agent_registry.require("support_agent"))

    async def fail_run(*, request: object, context: object) -> object:
        _ = request
        _ = context
        raise AgentPolicyDeniedError(
            "Tool 'documents.search' is not allowed by policy.",
            metadata={"policy_block_summary": "Tool 'documents.search' is not allowed by policy."},
        )

    agent.run = fail_run  # type: ignore[method-assign]

    request, context = build_request()

    result = await runtime.run_turn(request=request, context=context)

    assert result.answer == "I couldn't complete that request because tool 'documents.search' is not allowed by policy."
    assert result.strategy_name == "fallback_answer"
    assert result.metadata["policy_denied"] is True
    assert result.metadata["policy_block_summary"] == "Tool 'documents.search' is not allowed by policy."
    assert trace_store.events[3].resolved_event_name == "strategy_fallback_used"
    assert trace_store.events[3].payload["policy_denied"] is True
    assert trace_store.events[3].payload["policy_block_summary"] == "Tool 'documents.search' is not allowed by policy."