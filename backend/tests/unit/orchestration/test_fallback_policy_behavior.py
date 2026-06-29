from __future__ import annotations

import pytest

from app.contracts.state import default_workflow_state
from app.orchestration.errors import OrchestrationDependencyUnavailableError, StrategyPolicyDeniedError
from app.orchestration.fallback import decide_fallback
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
                        "message": "Fallback message",
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
                }
            },
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
    session_id = "session_fallback_policy"
    trace_id = "trace_fallback_policy"
    return (
        OrchestrationRequest(
            session_id=session_id,
            trace_id=trace_id,
            user_id="user_1",
            message="hello",
            usecase="default_chat",
            workflow_state=workflow_state_snapshot_from_document(
                session_id=session_id,
                state=default_workflow_state(session_id),
            ),
        ),
        OrchestrationRuntimeContext(
            request_id="request_fallback_policy",
            trace_id=trace_id,
            session_id=session_id,
            user_id="user_1",
        ),
    )


def test_decide_fallback_denies_policy_denials_and_same_strategy_loops() -> None:
    denied = decide_fallback(
        StrategyPolicyDeniedError(),
        failed_strategy="direct_agent",
        fallback_strategy="fallback_answer",
    )
    assert denied.allowed is False
    assert denied.reason == "policy_denied"

    looped = decide_fallback(
        OrchestrationDependencyUnavailableError(),
        failed_strategy="fallback_answer",
        fallback_strategy="fallback_answer",
    )
    assert looped.allowed is False
    assert looped.reason == "fallback_loop"


@pytest.mark.asyncio
async def test_runtime_does_not_fallback_after_primary_strategy_policy_denial() -> None:
    trace_store = FakeTraceStore()
    runtime = DefaultOrchestrationRuntime.from_config(
        config=build_config(),
        llm_gateway=FakeLLMGateway(response_text="should not be used"),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=trace_store,
        policy_service=FakePolicyService(denied_resources={"direct_agent"}),
    )
    request, context = build_request()

    with pytest.raises(StrategyPolicyDeniedError):
        await runtime.run_turn(request=request, context=context)

    assert [event.resolved_event_name for event in trace_store.events] == [
        "orchestration_started",
        "orchestration_failed",
    ]