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
                        "default_agent": "support_agent",
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
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "llm_profile": "usecase_profile",
                        "policy_profile": "default",
                    }
                },
            },
            "agents": {
                "defaults": {
                    "enabled": True,
                    "stream_llm_deltas": True,
                    "expose_agent_metadata": True,
                    "strict_prompt_profile_validation": True,
                    "known_prompt_profiles": ["general_assistant_v1"],
                    "max_output_chars": 12000,
                    "max_llm_calls": 1,
                },
                "plugins": {
                    "support_agent": {
                        "enabled": True,
                        "type": "general_assistant",
                        "display_name": "Support Agent",
                        "description": "General purpose assistant.",
                        "llm_profile": "agent_profile",
                        "prompt_profile": "general_assistant_v1",
                        "capabilities": {
                            "answer": True,
                            "stream": True,
                            "memory_read": False,
                            "memory_write": False,
                            "tool_intents": False,
                            "tool_execute": False,
                            "self_managed_memory": False,
                            "self_managed_tools": False,
                        },
                    }
                },
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
async def test_direct_runtime_invokes_builtin_general_assistant() -> None:
    config = build_config()
    llm = FakeLLMGateway(response_text="runtime builtin answer")
    trace_store = FakeTraceStore()
    tools = FakeToolGateway()
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=llm,
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=trace_store,
        policy_service=FakePolicyService(),
        tools=tools,
    )

    session_id = "session_general_assistant_runtime"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_general_assistant_runtime",
        user_id="user_1",
        message="Explain phase four.",
        usecase="default_chat",
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_general_assistant_runtime",
        trace_id="trace_general_assistant_runtime",
        session_id=session_id,
        user_id="user_1",
    )

    result = await runtime.run_turn(request=request, context=context)

    assert result.answer == "runtime builtin answer"
    assert result.strategy_name == "direct_agent"
    assert result.agent_name == "support_agent"
    assert result.llm_profile == "usecase_profile"
    assert llm.requests[0].profile == "usecase_profile"
    assert tools.calls == []
    assert trace_store.events
    assert "agent_completed" in [event.resolved_event_name for event in trace_store.events]