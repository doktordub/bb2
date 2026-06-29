from __future__ import annotations

from typing import cast

import pytest

from app.contracts.state import default_workflow_state
from app.orchestration.models import OrchestrationRequest, OrchestrationRuntimeContext
from app.orchestration.runtime import DirectAgentOrchestrationRuntime
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
async def test_runtime_context_uses_snapshot_and_recorder_facade_instead_of_stores() -> None:
    config = build_config()
    workflow_state = FakeWorkflowStateStore()
    trace_store = FakeTraceStore()
    runtime = DirectAgentOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=FakeLLMGateway(response_text="No direct persistence"),
        memory=FakeMemoryGateway(),
        state=workflow_state,
        trace=trace_store,
        policy_service=FakePolicyService(),
    )

    session_id = "session_runtime_persistence_1"
    state_document = default_workflow_state(session_id)
    state_document["conversation"]["messages"] = [{"role": "user", "content": "existing"}]
    snapshot = workflow_state_snapshot_from_document(session_id=session_id, state=state_document)
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_runtime_persistence_1",
        user_id="user_1",
        message="show safe context",
        usecase="default_chat",
        metadata={"request_id": "request_runtime_persistence_1"},
        workflow_state=snapshot,
    )
    context = OrchestrationRuntimeContext(
        request_id="request_runtime_persistence_1",
        trace_id="trace_runtime_persistence_1",
        session_id=session_id,
        user_id="user_1",
    )

    result = await runtime.run_turn(request=request, context=context)

    assert workflow_state.load_requests == []
    assert workflow_state.save_requests == []
    assert result.state_delta is not None

    agent = cast(FakeAgent, runtime.agent_registry.require("support_agent"))
    orchestration_context = agent.runs[0]

    assert orchestration_context.state == snapshot
    assert orchestration_context.observability is runtime.trace_recorder
    assert orchestration_context.trace is not trace_store
    assert orchestration_context.runtime is not None
    assert orchestration_context.runtime.request_id == "request_runtime_persistence_1"
    assert orchestration_context.limits is not None
    assert orchestration_context.limits.turns_started == 1