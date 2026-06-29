from __future__ import annotations

import asyncio
from typing import cast

import pytest

from app.contracts.state import default_workflow_state
from app.orchestration.errors import OrchestrationCancelledError
from app.orchestration.models import OrchestrationRequest, OrchestrationRuntimeContext
from app.orchestration.runtime import DefaultOrchestrationRuntime
from app.orchestration.state_delta import workflow_state_snapshot_from_document
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
                    "fallback_strategy": "direct_agent",
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
                    }
                },
                "usecases": {
                    "default_chat": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
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


@pytest.mark.asyncio
async def test_default_runtime_run_turn_builds_safe_result_and_health_surface() -> None:
    config = build_config()
    trace_store = FakeTraceStore()
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=FakeLLMGateway(response_text="Hello from runtime"),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=trace_store,
        policy_service=FakePolicyService(),
    )

    session_id = "session_runtime_1"
    trace_id = "trace_runtime_1"
    runtime_request = OrchestrationRequest(
        session_id=session_id,
        trace_id=trace_id,
        user_id="user_1",
        message="hello runtime",
        usecase="default_chat",
        metadata={"request_id": "request_runtime_1"},
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    runtime_context = OrchestrationRuntimeContext(
        request_id="request_runtime_1",
        trace_id=trace_id,
        session_id=session_id,
        user_id="user_1",
        project_id="project_1",
        tenant_id="tenant_1",
    )

    result = await runtime.run_turn(request=runtime_request, context=runtime_context)

    assert result.answer == "Hello from runtime"
    assert result.usecase == "default_chat"
    assert result.strategy_name == "direct_agent"
    assert result.agent_name == "support_agent"
    assert result.state_delta is not None
    assert result.state_delta.set_active_usecase == "default_chat"
    assert result.state_delta.set_active_agent == "support_agent"
    assert [message.content for message in result.state_delta.append_messages] == ["Hello from runtime"]
    assert result.steps[0].step_type == "strategy"

    recorded_names = [event.resolved_event_name for event in trace_store.events]
    assert recorded_names == ["orchestration_started", "strategy_selected", "orchestration_completed"]

    agent = cast(FakeAgent, runtime.agent_registry.require("support_agent"))
    assert agent.runs[0].runtime is not None
    assert agent.runs[0].runtime.request_id == "request_runtime_1"
    assert agent.runs[0].limits is not None
    assert agent.runs[0].limits.turns_started == 1

    health = await runtime.health()
    capabilities = await runtime.capabilities()

    assert health.status == "ok"
    assert health.registered_strategy_count == 1
    assert capabilities.default_strategy == "direct_agent"
    assert capabilities.usecases[0].name == "default_chat"
    assert capabilities.strategies[0].name == "direct_agent"


@pytest.mark.asyncio
async def test_default_runtime_run_turn_raises_cancelled_error_before_execution() -> None:
    config = build_config()
    trace_store = FakeTraceStore()
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=FakeLLMGateway(response_text="ignored"),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=trace_store,
        policy_service=FakePolicyService(),
    )

    cancellation_token = asyncio.Event()
    cancellation_token.set()
    runtime_request = OrchestrationRequest(
        session_id="session_runtime_cancelled",
        trace_id="trace_runtime_cancelled",
        user_id="user_1",
        message="hello runtime",
        usecase="default_chat",
    )
    runtime_context = OrchestrationRuntimeContext(
        request_id="request_runtime_cancelled",
        trace_id="trace_runtime_cancelled",
        session_id="session_runtime_cancelled",
        user_id="user_1",
        cancellation_token=cancellation_token,
    )

    with pytest.raises(OrchestrationCancelledError):
        await runtime.run_turn(request=runtime_request, context=runtime_context)

    assert [event.resolved_event_name for event in trace_store.events] == ["orchestration_cancelled"]