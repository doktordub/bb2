from __future__ import annotations

import pytest

from app.config.view import get_orchestration_settings
from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.tools import (
    ToolDefinition,
    ToolExecutionResult,
    ToolResultContent,
    ToolResultSummary,
)
from app.orchestration.errors import OrchestrationLimitExceededError
from app.orchestration.limits import OrchestrationLimitTracker
from app.orchestration.models import OrchestrationRuntimeContext
from app.orchestration.strategies.tool_assisted import ToolAssistedStrategy
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
        }
    )


def build_context(
    config: FakeConfigurationView,
    *,
    llm: FakeLLMGateway,
    tools: FakeToolGateway,
) -> OrchestrationContext:
    settings = get_orchestration_settings(config)
    strategy_settings = settings.strategies["tool_assisted"]
    limits = OrchestrationLimitTracker.from_settings(settings, strategy_settings)
    limits.mark_turn_started()
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="tool: architecture notes",
            usecase="project_work",
            trace_id="trace_1",
        ),
        llm=llm,
        memory=FakeMemoryGateway(),
        state=None,
        tools=tools,
        trace=FakeTraceStore(),
        policy=FakePolicyService(),
        config=config,
        runtime_metadata={
            "agent_name": "support_agent",
            "strategy_name": "tool_assisted",
            "llm_profile": "tool_profile",
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
async def test_tool_assisted_strategy_executes_one_bounded_tool_then_summarizes() -> None:
    config = build_config()
    llm = FakeLLMGateway(response_text="tool assisted answer")
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

    result = await ToolAssistedStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.answer == "tool assisted answer"
    assert result.strategy_name == "tool_assisted"
    assert result.llm_profile == "tool_profile"
    assert tools.calls[0].tool_name == "documents.search"
    assert result.tool_calls[0]["tool_name"] == "documents.search"
    assert [step["step_type"] for step in result.metadata["steps"]] == ["agent", "tool", "agent"]
    assert "Found architecture notes" in llm.requests[0].messages[0].content


@pytest.mark.asyncio
async def test_tool_assisted_strategy_rejects_identical_tool_repetition() -> None:
    config = build_config()
    llm = FakeLLMGateway(response_text="tool assisted answer")
    tools = FakeToolGateway(
        tools=[ToolDefinition(name="documents.search", description="Search documents")]
    )
    context = build_context(config, llm=llm, tools=tools)
    context.metadata["tool_signatures"] = [
        "documents.search:[('limit', 3), ('query', 'architecture notes')]"
    ]

    with pytest.raises(OrchestrationLimitExceededError):
        await ToolAssistedStrategy().run(
            context=context,
            agents=[FakeAgent(name="support_agent")],
        )


@pytest.mark.asyncio
async def test_tool_assisted_strategy_short_circuits_weather_search_without_llm() -> None:
    config = FakeConfigurationView(
        {
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
                        "tools": {"allowed_tools": ["websearch.search"], "max_calls": 2},
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
                        "tools": {"enabled": True, "allowed_tools": ["websearch.search"]},
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "allowed_tools": ["websearch.search"],
                }
            },
            "llm": {"defaults": {"profile": "gateway_default"}},
        }
    )
    llm = FakeLLMGateway(response_text="unused")
    tools = FakeToolGateway(
        tools=[
            ToolDefinition(
                name="websearch.search",
                description="Search the web.",
                execution_modes=("sync",),
                safety_level="read_only",
            )
        ],
        execution_results={
            "websearch.search": ToolExecutionResult(
                tool_name="websearch.search",
                status="completed",
                structured_content={
                    "ok": True,
                    "query": "What is the current weather in Dallas TX?",
                    "provider": "ddgs",
                    "backend": "duckduckgo",
                    "region": "us-en",
                    "safesearch": "moderate",
                    "time_limit": None,
                    "max_results": 3,
                    "result_count": 1,
                    "results": [
                        {
                            "rank": 1,
                            "title": "Dallas, TX Weather Forecasts",
                            "url": "https://example.test/weather",
                            "snippet": "Current weather conditions and hourly forecast for Dallas, TX.",
                            "source": "DuckDuckGo",
                        }
                    ],
                    "cached": False,
                    "error": None,
                },
                summary=ToolResultSummary(result_count=1),
            )
        },
    )
    context = build_context(config, llm=llm, tools=tools)
    context.request.message = "What is the current weather in Dallas TX?"

    result = await ToolAssistedStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_agent")],
    )

    assert result.strategy_name == "tool_assisted"
    assert tools.calls[0].tool_name == "websearch.search"
    assert tools.calls[0].arguments == {
        "query": "What is the current weather in Dallas TX?",
        "max_results": 3,
    }
    assert "Here are the top web results:" in result.answer
    assert "Dallas, TX Weather Forecasts" in result.answer
    assert llm.requests == []


@pytest.mark.asyncio
async def test_tool_assisted_strategy_uses_direct_answer_agent_for_basic_web_chat_requests() -> None:
    config = FakeConfigurationView(
        {
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
                        "default_agent": "support_web_agent",
                        "allowed_usecases": ["project_work"],
                        "llm_profile": "tool_profile",
                        "tools_enabled": True,
                        "tools": {"allowed_tools": ["websearch.search"], "max_calls": 2},
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
                        "agent": "support_web_agent",
                        "allowed_agents": ["support_agent", "support_web_agent"],
                        "llm_profile": "tool_profile",
                        "policy_profile": "default",
                        "memory": {"enabled": False, "include_document_chunks": False, "default_limit": 0},
                        "tools": {"enabled": True, "allowed_tools": ["websearch.search"]},
                    }
                },
            },
            "agents": {
                "support_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                },
                "support_web_agent": {
                    "enabled": True,
                    "module": "app.testing.fakes.fake_agent",
                    "class_name": "FakeAgent",
                    "allowed_tools": ["websearch.search"],
                },
            },
            "llm": {"defaults": {"profile": "gateway_default"}},
        }
    )
    llm = FakeLLMGateway(response_text="First, check CPU, logs, and recent deploys.")
    tools = FakeToolGateway(
        tools=[
            ToolDefinition(
                name="websearch.search",
                description="Search the web.",
                execution_modes=("sync",),
                safety_level="read_only",
            )
        ]
    )
    context = build_context(config, llm=llm, tools=tools)
    context.request.message = "My app is running slowly. Give me three first troubleshooting steps."
    context.runtime_metadata["agent_name"] = "support_web_agent"

    result = await ToolAssistedStrategy().run(
        context=context,
        agents=[FakeAgent(name="support_web_agent"), FakeAgent(name="support_agent")],
    )

    assert result.answer == "First, check CPU, logs, and recent deploys."
    assert result.agent_name == "support_agent"
    assert result.metadata["direct_answer_shortcut"] is True
    assert result.metadata["direct_answer_agent"] == "support_agent"
    assert result.metadata["tool_planning_agent"] == "support_web_agent"
    assert tools.calls == []
    assert llm.requests[0].profile == "tool_profile"