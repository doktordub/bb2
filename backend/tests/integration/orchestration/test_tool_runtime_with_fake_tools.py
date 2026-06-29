from __future__ import annotations

import pytest

from app.contracts.state import default_workflow_state
from app.contracts.tools import ToolDefinition, ToolExecutionResult, ToolResultContent, ToolResultSummary
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
            "app": {"active_usecase": "project_work"},
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "tool_assisted",
                    "fallback_strategy": "direct_agent",
                    "max_steps": 8,
                    "max_tool_calls": 2,
                    "max_memory_searches": 3,
                    "max_llm_calls": 6,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                },
                "strategies": {
                    "tool_assisted": {
                        "enabled": True,
                        "type": "tool_assisted",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["project_work"],
                        "llm_profile": "tool_profile",
                        "tools_enabled": True,
                        "tools": {"allowed_tools": ["documents.search"], "max_calls": 2},
                    },
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["project_work"],
                    },
                },
                "usecases": {
                    "project_work": {
                        "enabled": True,
                        "strategy": "tool_assisted",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "llm_profile": "tool_profile",
                        "policy_profile": "default",
                        "memory": {"enabled": False, "include_document_chunks": False, "default_limit": 0},
                        "tools": {"enabled": True, "allowed_tools": ["documents.search"]},
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "allowed_tools": ["documents.search"],
                }
            },
            "llm": {"defaults": {"profile": "gateway_default"}},
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
async def test_tool_runtime_executes_fake_tool_and_returns_safe_summary() -> None:
    config = build_config()
    tools = FakeToolGateway(
        tools=[ToolDefinition(name="documents.search", description="Search documents")],
        execution_results={
            "documents.search": ToolExecutionResult(
                tool_name="documents.search",
                status="completed",
                content=[ToolResultContent(type="text", text="Found architecture notes")],
                summary=ToolResultSummary(safe_message="Found architecture notes"),
            )
        },
    )
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=FakeLLMGateway(response_text="runtime tool answer"),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        trace=FakeTraceStore(),
        policy_service=FakePolicyService(),
        tools=tools,
    )

    session_id = "session_tool_runtime"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_tool_runtime",
        user_id="user_1",
        message="tool: architecture notes",
        usecase="project_work",
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_tool_runtime",
        trace_id="trace_tool_runtime",
        session_id=session_id,
        user_id="user_1",
        project_id="project_1",
    )

    result = await runtime.run_turn(request=request, context=context)

    assert result.answer == "runtime tool answer"
    assert result.strategy_name == "tool_assisted"
    assert [step.step_type for step in result.steps] == ["strategy", "agent", "tool", "agent"]
    assert result.tool_calls[0].tool_name == "documents.search"
    assert tools.calls[0].tool_name == "documents.search"