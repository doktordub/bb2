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
                        "tools": {
                            "enabled": True,
                            "allowed_tools": ["documents.search"],
                        },
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "llm_profile": "agent_profile",
                    "allowed_tools": ["documents.search"],
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
async def test_direct_runtime_uses_direct_strategy_and_keeps_tools_disabled_by_default() -> None:
    config = build_config()
    llm = FakeLLMGateway(response_text="runtime direct answer")
    tools = FakeToolGateway()
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=llm,
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=FakeTraceStore(),
        policy_service=FakePolicyService(),
        tools=tools,
    )

    session_id = "session_direct_runtime"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_direct_runtime",
        user_id="user_1",
        message="tool: architecture",
        usecase="default_chat",
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_direct_runtime",
        trace_id="trace_direct_runtime",
        session_id=session_id,
        user_id="user_1",
    )

    result = await runtime.run_turn(request=request, context=context)

    assert result.answer == "runtime direct answer"
    assert result.strategy_name == "direct_agent"
    assert result.agent_name == "support_agent"
    assert result.llm_profile == "usecase_profile"
    assert [step.step_type for step in result.steps] == ["strategy", "agent"]
    assert llm.requests[0].profile == "usecase_profile"
    assert tools.calls == []
    assert result.state_delta is not None