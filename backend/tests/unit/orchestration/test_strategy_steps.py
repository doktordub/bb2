from __future__ import annotations

import pytest

from app.config.view import ValidatedConfigurationView, get_orchestration_settings
from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.llm import LLMMessage, LLMRequest
from app.contracts.memory import MemoryResult, MemoryScope, MemorySearchRequest
from app.memory.adapters.fake import FakeMemoryAdapter
from app.contracts.tools import ToolDefinition, ToolExecutionRequest, ToolExecutionResult, ToolResultContent, ToolResultSummary, ToolScopes
from app.orchestration.limits import OrchestrationLimitTracker
from app.orchestration.models import OrchestrationRuntimeContext
from app.orchestration.strategy_steps import finalize_strategy_result, run_llm_completion_step, run_memory_search_step, run_tool_call_step
from app.policy.service import DefaultPolicyService
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
)
from tests.unit.memory.support import build_gateway, build_project_scope_config


def build_config() -> FakeConfigurationView:
    return FakeConfigurationView(
        {
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "retrieval_augmented",
                    "fallback_strategy": "direct_agent",
                    "max_steps": 8,
                    "max_tool_calls": 2,
                    "max_memory_searches": 3,
                    "max_llm_calls": 6,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                },
                "strategies": {
                    "retrieval_augmented": {
                        "enabled": True,
                        "type": "retrieval_augmented",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["document_chat"],
                        "llm_profile": "retrieval_profile",
                        "memory_enabled": True,
                        "tools_enabled": True,
                        "memory": {"default_limit": 2},
                        "tools": {"allowed_tools": ["documents.search"], "max_calls": 2},
                    }
                },
                "usecases": {
                    "document_chat": {
                        "enabled": True,
                        "strategy": "retrieval_augmented",
                        "agent": "support_agent",
                        "allowed_agents": ["support_agent"],
                        "llm_profile": "retrieval_profile",
                        "policy_profile": "default",
                        "memory": {"enabled": True, "include_document_chunks": True, "default_limit": 2},
                        "tools": {"enabled": True, "allowed_tools": ["documents.search"]},
                    }
                },
            },
            "llm": {"defaults": {"profile": "retrieval_profile"}},
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "allowed_tools": ["documents.search"],
                }
            },
        }
    )


def build_context(
    config: FakeConfigurationView,
    *,
    llm: FakeLLMGateway,
    memory: FakeMemoryGateway,
    tools: FakeToolGateway,
    policy: FakePolicyService,
) -> OrchestrationContext:
    settings = get_orchestration_settings(config)
    strategy_settings = settings.strategies["retrieval_augmented"]
    limits = OrchestrationLimitTracker.from_settings(settings, strategy_settings)
    limits.mark_turn_started()
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Summarize the architecture",
            usecase="document_chat",
            trace_id="trace_1",
        ),
        llm=llm,
        memory=memory,
        state=None,
        tools=tools,
        trace=FakeTraceStore(),
        policy=policy,
        config=config,
        runtime_metadata={
            "agent_name": "support_agent",
            "strategy_name": "retrieval_augmented",
            "llm_profile": "retrieval_profile",
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
async def test_run_memory_search_step_records_policy_and_summary() -> None:
    config = build_config()
    context = build_context(
        config,
        llm=FakeLLMGateway(response_text="unused"),
        memory=FakeMemoryGateway(
            results=[
                MemoryResult(
                    memory_id="memory_1",
                    text="The runtime resolves strategies through a registry.",
                    memory_type="document_chunk",
                    source_id="architecture.md",
                )
            ]
        ),
        tools=FakeToolGateway(),
        policy=FakePolicyService(),
    )

    result, summary = await run_memory_search_step(
        context,
        component="test.memory",
        request=MemorySearchRequest(
            text=context.request.message,
            scope=context.request and context.request and context.memory.search_result.results[0].record.scope if False else context.memory.search_result.results[0].record.scope,
        ),
        agent_name="support_agent",
        strategy_name="retrieval_augmented",
    )

    assert len(result.results) == 1
    assert summary.result_count == 1
    assert context.limits is not None and context.limits.memory_searches_used == 1
    assert context.policy.requests[0].action == "memory.search"


@pytest.mark.asyncio
async def test_run_memory_search_step_resolves_project_scope_before_real_policy_check() -> None:
    values = build_project_scope_config(
        usecase_name="architecture_document_qa",
        agent_name="architecture_document_agent",
        strategy_name="retrieval_augmented",
        strategy_type="retrieval_augmented",
        usecase_allowed_project_ids=("arch_docs",),
        usecase_default_project_id="arch_docs",
        agent_allowed_project_ids=("arch_docs",),
        agent_default_project_id="arch_docs",
    )
    values["orchestration"]["enabled"] = True
    values["orchestration"]["defaults"].update(
        {
            "max_steps": 8,
            "max_tool_calls": 2,
            "max_memory_searches": 3,
            "max_llm_calls": 6,
            "max_turn_duration_seconds": 120,
            "max_stream_duration_seconds": 300,
        }
    )
    values["orchestration"]["strategies"]["retrieval_augmented"].update(
        {
            "allowed_usecases": ["architecture_document_qa"],
            "memory_enabled": True,
            "tools_enabled": False,
            "memory": {
                "default_limit": 2,
                "include_document_chunks": True,
                "include_user_memory": True,
            },
        }
    )
    values["policy"] = {
        "default_profile": "default",
        "profiles": {
            "default": {
                "enabled": True,
                "deny_unknown_tools": True,
                "deny_unknown_llm_profiles": True,
                "require_memory_scope": True,
                "allow_memory_writes": True,
                "memory": {
                    "allowed_read_scopes": ["project", "user", "usecase"],
                    "allowed_write_scopes": [],
                },
            }
        },
    }
    config = ValidatedConfigurationView(values)
    settings = get_orchestration_settings(config)
    strategy_settings = settings.strategies["retrieval_augmented"]
    limits = OrchestrationLimitTracker.from_settings(settings, strategy_settings)
    limits.mark_turn_started()
    adapter = FakeMemoryAdapter(
        results=[
            MemoryResult(
                memory_id="memory_1",
                text="Architecture guidance for the backend memory scope.",
                memory_type="document_chunk",
            )
        ]
    )
    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="Summarize the architecture",
            usecase="architecture_document_qa",
            trace_id="trace_1",
        ),
        llm=FakeLLMGateway(response_text="unused"),
        memory=build_gateway(adapter=adapter, default_scope="project", limit_max=8),
        state=None,
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=DefaultPolicyService(config),
        config=config,
        runtime_metadata={
            "agent_name": "architecture_document_agent",
            "strategy_name": "retrieval_augmented",
            "usecase_name": "architecture_document_qa",
        },
        runtime=OrchestrationRuntimeContext(
            request_id="request_1",
            trace_id="trace_1",
            session_id="session_1",
            user_id="user_1",
            project_id=None,
        ),
        settings=settings,
        strategy_settings=strategy_settings,
        limits=limits,
    )

    result, summary = await run_memory_search_step(
        context,
        component="orchestration.strategy.retrieval_augmented",
        request=MemorySearchRequest(
            text=context.request.message,
            scope=MemoryScope(),
            limit=2,
            include_document_chunks=True,
        ),
        agent_name="architecture_document_agent",
        strategy_name="retrieval_augmented",
    )

    assert len(result.results) == 1
    assert summary.result_count == 1
    assert adapter.search_requests[0].scope.project_id == "arch_docs"


@pytest.mark.asyncio
async def test_run_tool_call_step_executes_tool_and_returns_safe_summary() -> None:
    config = build_config()
    tool_definition = ToolDefinition(name="documents.search", description="Search indexed documents.")
    context = build_context(
        config,
        llm=FakeLLMGateway(response_text="unused"),
        memory=FakeMemoryGateway(),
        tools=FakeToolGateway(
            tools=[tool_definition],
            execution_results={
                "documents.search": ToolExecutionResult(
                    tool_name="documents.search",
                    status="completed",
                    content=[ToolResultContent(type="text", text="Found architecture notes")],
                    summary=ToolResultSummary(safe_message="Found architecture notes"),
                )
            },
        ),
        policy=FakePolicyService(),
    )

    result, summary = await run_tool_call_step(
        context,
        component="test.tools",
        request=ToolExecutionRequest(
            tool_name="documents.search",
            arguments={"query": "architecture notes", "limit": 3},
            scopes=ToolScopes(session_id="session_1", agent_name="support_agent"),
        ),
        agent_name="support_agent",
        strategy_name="retrieval_augmented",
        tool_definition=tool_definition,
    )

    assert result.tool_name == "documents.search"
    assert summary.safe_message == "Found architecture notes"
    assert context.limits is not None and context.limits.tool_calls_used == 1
    assert context.policy.requests[0].action == "tool.execute"


@pytest.mark.asyncio
async def test_run_llm_completion_step_consumes_limits_and_returns_response() -> None:
    config = build_config()
    llm = FakeLLMGateway(response_text="grounded answer")
    context = build_context(
        config,
        llm=llm,
        memory=FakeMemoryGateway(),
        tools=FakeToolGateway(),
        policy=FakePolicyService(),
    )

    response = await run_llm_completion_step(
        context,
        component="test.llm",
        request=LLMRequest(
            profile="retrieval_profile",
            messages=[LLMMessage(role="user", content="hello")],
        ),
        agent_name="support_agent",
        strategy_name="retrieval_augmented",
    )

    assert response.text == "grounded answer"
    assert context.limits is not None and context.limits.llm_calls_used == 1
    assert context.policy.requests[0].action == "llm.complete"


def test_finalize_strategy_result_preserves_safe_summaries() -> None:
    result = finalize_strategy_result(
        answer="done",
        agent_name="support_agent",
        llm_profile="retrieval_profile",
        finish_reason="completed",
        metadata={"raw_payload": "filtered", "safe": "kept"},
    )

    assert result.answer == "done"
    assert result.finish_reason == "completed"
    assert result.metadata == {"safe": "kept"}