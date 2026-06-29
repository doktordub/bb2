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
            "app": {"active_usecase": "memory_capture"},
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
                        "default_agent": "memory_agent",
                        "allowed_usecases": ["memory_capture"],
                        "llm_profile": "strategy_profile",
                        "memory_enabled": True,
                        "tools_enabled": False,
                    }
                },
                "usecases": {
                    "memory_capture": {
                        "enabled": True,
                        "strategy": "direct_agent",
                        "agent": "memory_agent",
                        "allowed_agents": ["memory_agent"],
                        "llm_profile": "memory_profile",
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
                    "known_prompt_profiles": ["memory_curator_v1"],
                    "max_output_chars": 400,
                    "max_llm_calls": 1,
                    "max_memory_candidates": 3,
                },
                "plugins": {
                    "memory_agent": {
                        "enabled": True,
                        "type": "memory_curator",
                        "display_name": "Memory Curator",
                        "description": "Extracts memory candidates.",
                        "llm_profile": "agent_profile",
                        "prompt_profile": "memory_curator_v1",
                        "capabilities": {
                            "answer": False,
                            "review": False,
                            "stream": False,
                            "memory_read": False,
                            "memory_write": False,
                            "memory_candidate_extract": True,
                            "tool_intents": False,
                            "tool_execute": False,
                        },
                        "allowed_memory_scopes": ["project", "user"],
                    }
                },
            },
            "llm": {"defaults": {"profile": "gateway_default"}},
            "memory": {"enabled": True},
        }
    )


@pytest.mark.asyncio
async def test_direct_runtime_invokes_builtin_memory_curator_without_writing_memory() -> None:
    config = build_config()
    llm = FakeLLMGateway(
        response_text=(
            '{"memory_candidates": ['
            '{"text": "Project root is backend/.", "memory_type": "project_fact", "scope": "project"}, '
            '{"text": "User prefers concise updates.", "memory_type": "preference", "scope": "user"}'
            ']}'
        )
    )
    memory = FakeMemoryGateway()
    trace_store = FakeTraceStore()
    runtime = DefaultOrchestrationRuntime.from_config(
        config=config,
        llm_gateway=llm,
        memory=memory,
        state=FakeWorkflowStateStore(),
        trace=trace_store,
        policy_service=FakePolicyService(),
        tools=FakeToolGateway(),
    )

    session_id = "session_memory_curator_runtime"
    request = OrchestrationRequest(
        session_id=session_id,
        trace_id="trace_memory_curator_runtime",
        user_id="user_1",
        message="Remember that the project root is backend/.",
        usecase="memory_capture",
        workflow_state=workflow_state_snapshot_from_document(
            session_id=session_id,
            state=default_workflow_state(session_id),
        ),
    )
    context = OrchestrationRuntimeContext(
        request_id="request_memory_curator_runtime",
        trace_id="trace_memory_curator_runtime",
        session_id=session_id,
        user_id="user_1",
        project_id="project_1",
    )

    result = await runtime.run_turn(request=request, context=context)

    assert result.agent_name == "memory_agent"
    assert result.metadata["candidate_count"] == 2
    assert result.metadata["memory_update_count"] == 2
    assert len(result.memory_updates) == 2
    assert memory.writes == []
    assert "agent_memory_candidate_created" in [event.resolved_event_name for event in trace_store.events]