from __future__ import annotations

import pytest

from app.config.view import get_orchestration_settings
from app.contracts.context import OrchestrationContext, RequestContext
from app.orchestration.errors import OrchestrationPlanValidationError
from app.orchestration.limits import OrchestrationLimitTracker
from app.orchestration.models import OrchestrationRuntimeContext
from app.orchestration.strategies.bounded_planner import BoundedPlannerStrategy
from app.testing.fakes import (
    FakeAgent,
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
)


def build_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "bounded_planner",
                    "fallback_strategy": "direct_agent",
                    "max_steps": 8,
                    "max_tool_calls": 2,
                    "max_memory_searches": 2,
                    "max_memory_writes": 1,
                    "max_llm_calls": 4,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                    "max_tool_loop_iterations": 2,
                    "max_context_bytes": 4000,
                },
                "strategies": {
                    "bounded_planner": {
                        "enabled": True,
                        "type": "bounded_planner",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["project_plan"],
                        "planner_llm_profile": "planner_profile",
                        "executor_llm_profile": "executor_profile",
                        "memory_enabled": True,
                        "tools_enabled": True,
                        "max_steps": 8,
                        "max_tool_calls": 2,
                        "max_memory_searches": 2,
                        "max_llm_calls": 4,
                        "max_context_bytes": 2000,
                        "max_plan_steps": 4,
                        "max_execute_steps": 4,
                        "max_tool_loop_iterations": 2,
                        "tools": {"allowed_tools": ["documents.search"], "max_calls": 2},
                    },
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["project_plan"],
                    },
                },
                "usecases": {
                    "project_plan": {
                        "enabled": True,
                        "strategy": "bounded_planner",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "allowed_strategies": ["bounded_planner", "direct_agent"],
                        "llm_profile": "executor_profile",
                        "policy_profile": "default",
                        "memory": {"enabled": True, "include_document_chunks": True, "default_limit": 2},
                        "tools": {"enabled": True, "allowed_tools": ["documents.search"]},
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
            "llm": {"defaults": {"profile": "gateway_default"}},
        }
    )


def build_context(
    config: FakeConfigurationView,
    *,
    metadata: dict[str, object],
) -> OrchestrationContext:
    settings = get_orchestration_settings(config)
    strategy_settings = settings.strategies["bounded_planner"]
    limits = OrchestrationLimitTracker.from_settings(settings, strategy_settings)
    limits.mark_turn_started()
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Find the architecture notes and summarize them.",
            usecase="project_plan",
            trace_id="trace_1",
            metadata=dict(metadata),
        ),
        llm=FakeLLMGateway(response_text="unused"),
        memory=FakeMemoryGateway(),
        state=None,
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=FakePolicyService(),
        config=config,
        runtime_metadata={
            "agent_name": "support_agent",
            "strategy_name": "bounded_planner",
            "llm_profile": "executor_profile",
        },
        runtime=OrchestrationRuntimeContext(
            request_id="request_1",
            trace_id="trace_1",
            session_id="session_1",
            user_id="user_1",
            project_id="project_1",
        ),
        settings=settings,
        strategy_settings=strategy_settings,
        limits=limits,
    )


@pytest.mark.asyncio
async def test_bounded_planner_rejects_unknown_action_before_execution() -> None:
    context = build_context(
        build_config(),
        metadata={
            "planner_plan": {
                "plan_id": "plan_invalid",
                "steps": [
                    {
                        "step_id": "step_1",
                        "action_type": "shell_exec",
                        "name": "shell_exec",
                        "inputs": {},
                    },
                    {
                        "step_id": "final_1",
                        "action_type": "finalize",
                        "name": "return_answer",
                        "inputs": {"answer": "unused"},
                    },
                ],
            }
        },
    )

    with pytest.raises(OrchestrationPlanValidationError):
        await BoundedPlannerStrategy().run(
            context=context,
            agents=[FakeAgent(name="support_agent")],
        )


@pytest.mark.asyncio
async def test_bounded_planner_rejects_unknown_tool_before_execution() -> None:
    context = build_context(
        build_config(),
        metadata={
            "planner_plan": {
                "plan_id": "plan_invalid_tool",
                "steps": [
                    {
                        "step_id": "tool_1",
                        "action_type": "tool_call",
                        "name": "mcp.raw.tool",
                        "inputs": {"arguments": {"query": "architecture notes"}},
                    },
                    {
                        "step_id": "final_1",
                        "action_type": "finalize",
                        "name": "return_answer",
                        "inputs": {"answer": "unused"},
                    },
                ],
            }
        },
    )

    with pytest.raises(OrchestrationPlanValidationError):
        await BoundedPlannerStrategy().run(
            context=context,
            agents=[FakeAgent(name="support_agent")],
        )