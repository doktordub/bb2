from __future__ import annotations

import json

import pytest

from app.config.view import get_orchestration_settings
from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.tools import ToolDefinition, ToolExecutionResult, ToolResultContent, ToolResultSummary
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
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


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
                    "allowed_tools": ["documents.search"],
                }
            },
            "llm": {"defaults": {"profile": "gateway_default"}},
        }
    )


def build_task_first_config() -> FakeConfigurationView:
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
                        "allowed_usecases": ["task_chat"],
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
                        "allowed_usecases": ["task_chat"],
                    },
                },
                "usecases": {
                    "task_chat": {
                        "enabled": True,
                        "strategy": "bounded_planner",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent", "task_execution_agent"],
                        "allowed_strategies": ["bounded_planner", "fallback_answer"],
                        "llm_profile": "executor_profile",
                        "policy_profile": "default",
                        "memory": {"enabled": True, "include_document_chunks": True, "default_limit": 2},
                        "tools": {"enabled": True, "allowed_tools": ["documents.search"]},
                        "metadata": {"routing_mode": "task_first", "assessment_agent": "task_execution_agent"},
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "allowed_tools": ["documents.search"],
                },
                "task_execution_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                },
            },
            "llm": {"defaults": {"profile": "gateway_default"}},
        }
    )


def build_context(
    config: FakeConfigurationView,
    *,
    llm: FakeLLMGateway,
    tools: FakeToolGateway | None = None,
    metadata: dict[str, object] | None = None,
) -> OrchestrationContext:
    settings = get_orchestration_settings(config)
    strategy_settings = settings.strategies["bounded_planner"]
    limits = OrchestrationLimitTracker.from_settings(settings, strategy_settings)
    limits.mark_turn_started()
    trace_store = FakeTraceStore()
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Find the architecture notes and summarize them.",
            usecase="project_plan",
            trace_id="trace_1",
            metadata=dict(metadata or {}),
        ),
        llm=llm,
        memory=FakeMemoryGateway(),
        state=None,
        tools=tools or FakeToolGateway(),
        trace=trace_store,
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
        observability=build_fake_trace_recorder(store=trace_store),
        limits=limits,
    )


def build_task_first_context(
    config: FakeConfigurationView,
    *,
    llm: FakeLLMGateway,
    tools: FakeToolGateway | None = None,
    metadata: dict[str, object] | None = None,
) -> OrchestrationContext:
    settings = get_orchestration_settings(config)
    strategy_settings = settings.strategies["bounded_planner"]
    limits = OrchestrationLimitTracker.from_settings(settings, strategy_settings)
    limits.mark_turn_started()
    trace_store = FakeTraceStore()
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Handle the current request safely.",
            usecase="task_chat",
            trace_id="trace_task_1",
            metadata=dict(metadata or {}),
        ),
        llm=llm,
        memory=FakeMemoryGateway(),
        state=None,
        tools=tools or FakeToolGateway(),
        trace=trace_store,
        policy=FakePolicyService(),
        config=config,
        runtime_metadata={
            "agent_name": "support_agent",
            "strategy_name": "bounded_planner",
            "llm_profile": "executor_profile",
        },
        runtime=OrchestrationRuntimeContext(
            request_id="request_task_1",
            trace_id="trace_task_1",
            session_id="session_1",
            user_id="user_1",
            project_id="project_1",
        ),
        settings=settings,
        strategy_settings=strategy_settings,
        observability=build_fake_trace_recorder(store=trace_store),
        limits=limits,
    )


@pytest.mark.asyncio
async def test_bounded_planner_strategy_executes_llm_generated_tool_plan() -> None:
    config = build_config()
    llm = FakeLLMGateway(
        response_text=json.dumps(
            {
                "plan_id": "plan_1",
                "safe_goal": "Find project notes.",
                "steps": [
                    {
                        "step_id": "tool_1",
                        "action_type": "tool_call",
                        "name": "documents.search",
                        "inputs": {"arguments": {"query": "architecture notes", "limit": 2}},
                    },
                    {
                        "step_id": "final_1",
                        "action_type": "finalize",
                        "name": "return_answer",
                        "inputs": {"template": "Summary: {last_output}"},
                    },
                ],
            }
        )
    )
    tools = FakeToolGateway(
        tools=[
            ToolDefinition(
                name="documents.search",
                description="Search indexed documents.",
                execution_modes=("sync",),
                safety_level="read_only",
            )
        ],
        execution_results={
            "documents.search": ToolExecutionResult(
                tool_name="documents.search",
                status="completed",
                content=[ToolResultContent(type="text", text="Found architecture notes")],
                summary=ToolResultSummary(safe_message="Found architecture notes"),
            )
        },
    )
    context = build_context(config, llm=llm, tools=tools)

    result = await BoundedPlannerStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.answer == "Summary: Found architecture notes"
    assert result.strategy_name == "bounded_planner"
    assert result.llm_profile == "planner_profile"
    assert tools.calls[0].tool_name == "documents.search"
    assert result.metadata["planner_source"] == "llm"
    assert result.metadata["plan_step_count"] == 2
    assert [step["step_type"] for step in result.metadata["steps"]] == ["plan", "tool_call", "finalize"]


@pytest.mark.asyncio
async def test_bounded_planner_strategy_executes_agent_invoke_step_from_metadata_plan() -> None:
    config = build_config()
    llm = FakeLLMGateway(response_text="agent answer")
    context = build_context(
        config,
        llm=llm,
        metadata={
            "planner_plan": {
                "plan_id": "plan_2",
                "steps": [
                    {
                        "step_id": "agent_1",
                        "action_type": "agent_invoke",
                        "name": "support_agent",
                        "inputs": {},
                    },
                    {
                        "step_id": "final_1",
                        "action_type": "finalize",
                        "name": "return_answer",
                        "inputs": {},
                    },
                ],
            }
        },
    )

    result = await BoundedPlannerStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.answer == "agent answer"
    assert result.metadata["planner_source"] == "request_metadata"
    assert [step["step_type"] for step in result.metadata["steps"]] == ["plan", "agent_invoke", "finalize"]


@pytest.mark.asyncio
async def test_bounded_planner_task_first_direct_answer_skips_plan_execution() -> None:
    config = build_task_first_config()
    llm = FakeLLMGateway(response_text="unused")
    tools = FakeToolGateway()
    context = build_task_first_context(
        config,
        llm=llm,
        tools=tools,
        metadata={
            "task_assessment": {
                "request_kind": "support_question",
                "response_mode": "direct_answer",
                "direct_answer_eligible": True,
                "direct_answer": "Start with CPU, memory, and disk checks, then inspect logs, then compare against recent deploys.",
                "missing_required_inputs": [],
                "required_deterministic_computations": [],
                "suggested_task_list": [],
                "preferred_agents": ["support_agent"],
                "preferred_tools": [],
                "visualization_intent": False,
            }
        },
    )

    result = await BoundedPlannerStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.answer.startswith("Start with CPU")
    assert result.metadata["response_mode"] == "direct_answer"
    assert result.metadata["finish_reason"] == "direct_answer"
    assert result.metadata["steps"][0]["step_type"] == "assessment"
    assert llm.requests == []
    assert tools.calls == []


@pytest.mark.asyncio
async def test_bounded_planner_task_first_requests_user_input_before_execution() -> None:
    config = build_task_first_config()
    llm = FakeLLMGateway(response_text="unused")
    tools = FakeToolGateway()
    context = build_task_first_context(
        config,
        llm=llm,
        tools=tools,
        metadata={
            "task_assessment": {
                "request_kind": "report_request",
                "response_mode": "request_user_input",
                "direct_answer_eligible": False,
                "clarification_question": "Which date range should I use?",
                "missing_required_inputs": ["date_range"],
                "required_deterministic_computations": [],
                "suggested_task_list": [],
                "preferred_agents": [],
                "preferred_tools": [],
                "visualization_intent": False,
            }
        },
    )

    result = await BoundedPlannerStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.answer == "Which date range should I use?"
    assert result.metadata["response_mode"] == "request_user_input"
    assert result.metadata["needs_user_input"] is True
    assert result.metadata["finish_reason"] == "needs_user_input"
    assert [step["step_type"] for step in result.metadata["steps"]] == ["assessment"]
    event_names = [event.resolved_event_name for event in context.trace.events]
    assert event_names == ["request_assessed", "clarification_requested", "task_blocked"]
    assert llm.requests == []
    assert tools.calls == []


@pytest.mark.asyncio
async def test_bounded_planner_task_first_executes_assessment_task_list() -> None:
    config = build_task_first_config()
    llm = FakeLLMGateway(response_text="unused")
    tools = FakeToolGateway(
        tools=[
            ToolDefinition(
                name="documents.search",
                description="Search indexed documents.",
                execution_modes=("sync",),
                safety_level="read_only",
            )
        ],
        execution_results={
            "documents.search": ToolExecutionResult(
                tool_name="documents.search",
                status="completed",
                content=[ToolResultContent(type="text", text="Found architecture notes")],
                summary=ToolResultSummary(safe_message="Found architecture notes"),
            )
        },
    )
    context = build_task_first_context(
        config,
        llm=llm,
        tools=tools,
        metadata={
            "task_assessment": {
                "request_kind": "document_lookup",
                "response_mode": "planned_execution",
                "direct_answer_eligible": False,
                "missing_required_inputs": [],
                "required_deterministic_computations": [],
                "suggested_task_list": [
                    {
                        "step_id": "tool_1",
                        "action_type": "tool_call",
                        "name": "documents.search",
                        "inputs": {"arguments": {"query": "architecture notes", "limit": 2}},
                    },
                    {
                        "step_id": "final_1",
                        "action_type": "finalize",
                        "name": "return_answer",
                        "inputs": {"template": "Summary: {last_output}"},
                    },
                ],
                "preferred_agents": ["support_agent"],
                "preferred_tools": ["documents.search"],
                "visualization_intent": False,
            }
        },
    )

    result = await BoundedPlannerStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.answer == "Summary: Found architecture notes"
    assert result.metadata["planner_source"] == "task_assessment"
    assert result.metadata["response_mode"] == "planned_execution"
    assert [step["step_type"] for step in result.metadata["steps"]] == [
        "assessment",
        "plan",
        "tool_call",
        "finalize",
    ]
    event_names = [event.resolved_event_name for event in context.trace.events]
    assert event_names == ["request_assessed", "task_list_generated", "task_completed"]


@pytest.mark.asyncio
async def test_bounded_planner_strategy_executes_terminal_request_user_input_step() -> None:
    config = build_config()
    context = build_context(
        config,
        llm=FakeLLMGateway(response_text="unused"),
        metadata={
            "planner_plan": {
                "plan_id": "plan_3",
                "steps": [
                    {
                        "step_id": "ask_1",
                        "action_type": "request_user_input",
                        "name": "ask_clarification",
                        "inputs": {
                            "question": "Which repository should I inspect?",
                            "missing_required_inputs": ["repository"],
                        },
                    }
                ],
            }
        },
    )

    result = await BoundedPlannerStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.answer == "Which repository should I inspect?"
    assert result.metadata["finish_reason"] == "needs_user_input"
    assert result.metadata["needs_user_input"] is True
    assert [step["step_type"] for step in result.metadata["steps"]] == ["plan", "request_user_input"]