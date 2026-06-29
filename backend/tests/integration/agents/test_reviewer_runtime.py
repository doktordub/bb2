from __future__ import annotations

import pytest

from app.contracts.state import default_workflow_state
from app.orchestration.models import OrchestrationRequest, OrchestrationRuntimeContext
from app.orchestration.runtime import DefaultOrchestrationRuntime
from app.orchestration.state_delta import workflow_state_snapshot_from_document
from app.testing.fakes import FakeConfigurationView, FakeLLMGateway, FakeMemoryGateway, FakePolicyService, FakeToolGateway, FakeTraceStore, FakeWorkflowStateStore


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
                        "default_agent": "review_agent",
                        "allowed_usecases": ["default_chat"],
                        "llm_profile": "strategy_profile",
                        "memory_enabled": False,
                        "tools_enabled": False,
                    }
                },
                "usecases": {
                    "default_chat": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "review_agent",
                        "allowed_agents": ["review_agent"],
                        "llm_profile": "review_profile",
                        "policy_profile": "default",
                    }
                },
            },
            "agents": {
                "defaults": {
                    "enabled": True,
                    "stream_llm_deltas": False,
                    "expose_agent_metadata": True,
                    "strict_prompt_profile_validation": True,
                    "known_prompt_profiles": ["reviewer_v1"],
                    "max_output_chars": 400,
                    "max_llm_calls": 1,
                },
                "plugins": {
                    "review_agent": {
                        "enabled": True,
                        "type": "reviewer",
                        "display_name": "Reviewer Agent",
                        "description": "Reviews candidate output.",
                        "llm_profile": "agent_profile",
                        "prompt_profile": "reviewer_v1",
                        "capabilities": {
                            "answer": False,
                            "review": True,
                            "stream": False,
                            "memory_read": False,
                            "memory_write": False,
                            "memory_candidate_extract": False,
                            "tool_intents": False,
                            "tool_execute": False,
                        },
                    }
                },
            },
            "llm": {"defaults": {"profile": "gateway_default"}},
            "memory": {"enabled": False},
        }
    )


@pytest.mark.asyncio
async def test_direct_runtime_invokes_builtin_reviewer_and_exposes_safe_review_metadata() -> None:
    config = build_config()
    llm = FakeLLMGateway(
        response_text=(
            '{"passed": false, "score": 0.3, '
            '"findings": ["Missing the validation command."], '
            '"suggested_revision": "Add the focused pytest gate."}'
        )
    )
    trace_store = FakeTraceStore()
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=llm,
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=trace_store,
        policy_service=FakePolicyService(),
        tools=FakeToolGateway(),
    )

    session_id = "session_reviewer_runtime"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_reviewer_runtime",
        user_id="user_1",
        message="Review the proposed phase summary.",
        usecase="default_chat",
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_reviewer_runtime",
        trace_id="trace_reviewer_runtime",
        session_id=session_id,
        user_id="user_1",
    )

    result = await runtime.run_turn(request=request, context=context)

    assert result.agent_name == "review_agent"
    assert result.metadata["review"]["passed"] is False
    assert result.metadata["review"]["score"] == 0.3
    assert result.metadata["review"]["findings"] == ["Missing the validation command."]
    assert result.metadata["review"]["suggested_revision"] == "Add the focused pytest gate."
    assert "agent_review_completed" in [event.resolved_event_name for event in trace_store.events]