from __future__ import annotations

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
    FakeToolGateway,
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
                },
                "strategies": {
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["default_chat"],
                        "llm_profile": "strategy_profile",
                    }
                },
                "usecases": {
                    "default_chat": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "llm_profile": "usecase_profile",
                        "policy_profile": "default",
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "llm_profile": "agent_profile",
                }
            },
            "llm": {"defaults": {"profile": "gateway_default"}},
            "memory": {"enabled": False},
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
async def test_direct_runtime_streaming_uses_same_agent_path_as_non_streaming() -> None:
    config = build_config()
    llm = FakeLLMGateway(response_text="streaming direct answer")
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=llm,
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=FakeTraceStore(),
        policy_service=FakePolicyService(),
        tools=FakeToolGateway(),
    )

    session_id = "session_direct_stream"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_direct_stream",
        user_id="user_1",
        message="hello",
        usecase="default_chat",
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_direct_stream",
        trace_id="trace_direct_stream",
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
    assert events[2].text == "streaming direct answer"
    assert events[3].result is not None
    assert events[3].result.answer == "streaming direct answer"
    assert events[3].result.llm_profile == "usecase_profile"
    assert events[4].metadata["finish_reason"] == "completed"
    assert llm.requests[0].profile == "usecase_profile"