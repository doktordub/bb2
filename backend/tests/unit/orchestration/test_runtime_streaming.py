from __future__ import annotations

import asyncio

import pytest

from app.contracts.state import default_workflow_state
from app.orchestration.models import OrchestrationRequest, OrchestrationRuntimeContext
from app.orchestration.runtime import DefaultOrchestrationRuntime
from app.orchestration.state_delta import workflow_state_snapshot_from_document
from app.testing.fakes import (
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
async def test_default_runtime_stream_turn_normalizes_strategy_streaming() -> None:
    config = build_config()
    trace_store = FakeTraceStore()
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=FakeLLMGateway(response_text="streamed answer"),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=trace_store,
        policy_service=FakePolicyService(),
    )

    session_id = "session_runtime_stream_1"
    trace_id = "trace_runtime_stream_1"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id=trace_id,
        user_id="user_1",
        message="stream please",
        usecase="default_chat",
        metadata={"request_id": "request_runtime_stream_1"},
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_runtime_stream_1",
        trace_id=trace_id,
        session_id=session_id,
        user_id="user_1",
    )

    events = [event async for event in runtime.stream_turn(request=request, context=context)]

    assert [event.type for event in events] == [
        "orchestration.started",
        "strategy.selected",
        "response.delta",
        "orchestration.completed",
        "response.completed",
    ]
    assert events[2].text == "streamed answer"
    assert events[3].result is not None
    assert events[3].result.answer == "streamed answer"
    assert events[3].result.state_delta is not None
    assert events[4].metadata["finish_reason"] == "completed"
    assert [event.resolved_event_name for event in trace_store.events] == [
        "orchestration_started",
        "strategy_selected",
        "orchestration_completed",
    ]


@pytest.mark.asyncio
async def test_default_runtime_stream_turn_emits_cancelled_event() -> None:
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
    request = OrchestrationRequest(
        session_id="session_runtime_stream_cancelled",
        trace_id="trace_runtime_stream_cancelled",
        user_id="user_1",
        message="cancel me",
        usecase="default_chat",
    )
    context = OrchestrationRuntimeContext(
        request_id="request_runtime_stream_cancelled",
        trace_id="trace_runtime_stream_cancelled",
        session_id="session_runtime_stream_cancelled",
        user_id="user_1",
        cancellation_token=cancellation_token,
    )

    events = [event async for event in runtime.stream_turn(request=request, context=context)]

    assert [event.type for event in events] == ["orchestration.cancelled"]
    assert [event.resolved_event_name for event in trace_store.events] == ["orchestration_cancelled"]