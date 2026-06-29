from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module
import socket
import sqlite3
import subprocess
import sys

import pytest

from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.llm import LLMMessage, LLMRequest
from app.contracts.memory import (
    MemoryGetRequest,
    MemoryResult,
    MemoryScope,
    MemorySearchRequest,
    MemoryWrite,
)
from app.contracts.policy import PolicyRequest
from app.contracts.tools import (
    ToolCallRequest,
    ToolExecutionRequest,
    ToolListFilters,
    ToolScopes,
    ToolSpec,
)
from app.contracts.trace import TraceEvent
from app.testing.fakes import (
    FakeConfigurationLoader,
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakePolicyService,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)


def build_context() -> OrchestrationContext:
    return OrchestrationContext(
        request=RequestContext(
            user_id="user_1",
            session_id="session_1",
            message="hello",
            usecase="support",
            trace_id="trace_1",
        ),
        llm=FakeLLMGateway(),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        tools=FakeToolGateway(),
        trace=FakeTraceStore(),
        policy=FakePolicyService(),
        config=FakeConfigurationView({"agents": {"fake_agent": {"enabled": True}}}),
        runtime_metadata={},
    )


def test_contract_modules_import_together() -> None:
    module_names = [
        "app.contracts.agents",
        "app.contracts.config",
        "app.contracts.context",
        "app.contracts.errors",
        "app.contracts.health",
        "app.contracts.llm",
        "app.contracts.memory",
        "app.contracts.policy",
        "app.contracts.results",
        "app.contracts.state",
        "app.contracts.strategies",
        "app.contracts.tools",
        "app.contracts.trace",
    ]

    for module_name in module_names:
        assert import_module(module_name) is not None


async def test_contract_slice_runs_without_concrete_infrastructure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Contract tests should not require concrete infrastructure")

    monkeypatch.setattr(socket, "create_connection", fail)
    monkeypatch.setattr(sqlite3, "connect", fail)
    monkeypatch.setattr(subprocess, "Popen", fail)

    forbidden_roots = ("agent_framework", "arcadedb", "mcp", "memory_store")
    initially_loaded = {
        name
        for name in sys.modules
        if any(name == root or name.startswith(f"{root}.") for root in forbidden_roots)
    }

    context = build_context()

    found = await context.memory.search(
        MemorySearchRequest(
            text=context.request.message,
            scope=MemoryScope(
                user_id=context.request.user_id,
                session_id=context.request.session_id,
            ),
        ),
        context,
    )
    listed = await context.tools.list_tools(context)
    await context.state.save(context.request.session_id, {"step": "contracts"})
    await context.trace.record_event(
        TraceEvent(
            trace_id=context.request.trace_id or "trace_1",
            session_id=context.request.session_id,
            event_type="contracts_checked",
            component="tests.contracts",
            timestamp=datetime.now(UTC),
        ),
    )
    decision = await context.policy.evaluate(
        PolicyRequest(
            action="contracts.validate",
            component="tests.contracts",
        ),
        context,
    )

    assert found.results == []
    assert listed == []
    assert context.state.states[context.request.session_id] == {"step": "contracts"}
    assert context.trace.events[0].component == "tests.contracts"
    assert decision.allowed is True

    loaded_modules = sorted(
        name
        for name in sys.modules
        if any(name == root or name.startswith(f"{root}.") for root in forbidden_roots)
        and name not in initially_loaded
    )

    assert loaded_modules == []


async def test_fake_dependencies_build_a_complete_orchestration_context() -> None:
    context = build_context()

    assert context.request.session_id == "session_1"
    assert (await context.state.health())["status"] == "ok"
    assert (await context.state.health())["provider"] == "fake"
    assert (await context.trace.health())["status"] == "ok"
    assert (await context.trace.health())["provider"] == "fake"
    assert (await context.memory.health()).status == "ok"
    assert (await context.memory.health()).provider == "fake"
    assert context.config.require("agents.fake_agent.enabled") is True


async def test_fake_memory_gateway_records_search_write_and_forget() -> None:
    result = MemoryResult(memory_id="memory_1", text="hello", memory_type="note")
    memory = FakeMemoryGateway(results=[result])
    context = build_context()

    search_request = MemorySearchRequest(
        text="hello",
        scope=MemoryScope(user_id="user_1", session_id="session_1"),
    )
    write = MemoryWrite(
        text="remember this",
        scope=MemoryScope(user_id="user_1", session_id="session_1"),
        memory_type="note",
        stable_key="note_1",
    )

    found = await memory.search(search_request, context)
    record = await memory.upsert(write, context)
    fetched = await memory.get(MemoryGetRequest(identifier="note_1"), context)
    await memory.forget(record.memory_id, context)
    stats = await memory.stats()

    assert found.results == [result]
    assert memory.search_requests == [search_request]
    assert memory.writes == [write]
    assert record.memory_id == "note_1"
    assert fetched is not None
    assert fetched.memory_id == "note_1"
    assert memory.forgotten_ids == ["note_1"]
    assert stats.total_records == 0


async def test_fake_tool_gateway_lists_tools_and_records_calls() -> None:
    tool = ToolSpec(
        name="documents.search",
        description="Search documents",
        input_schema={"type": "object"},
        source="fake",
        execution_modes=["sync", "stream"],
        tags=["search"],
    )
    tools = FakeToolGateway(tools=[tool])
    context = build_context()

    listed = await tools.list_tools(
        context,
        ToolListFilters(tags=["search"], execution_mode="stream", enabled_only=True),
    )
    resolved = await tools.get_tool("documents.search", context)
    result = await tools.execute(
        ToolExecutionRequest(
            tool_name="documents.search",
            arguments={"query": "policy"},
            scopes=ToolScopes(project_id="proj-1"),
        ),
        context,
    )
    compatibility_result = await tools.call_tool(
        ToolCallRequest(tool_name="documents.search", arguments={"query": "policy"}),
        context,
    )
    stream_events = [
        event
        async for event in tools.stream_execute(
            ToolExecutionRequest(
                tool_name="documents.search",
                arguments={"query": "policy"},
                scopes=ToolScopes(project_id="proj-1"),
                stream=True,
            ),
            context,
        )
    ]
    health = await tools.health()
    capabilities = await tools.capabilities()

    assert listed == [tool]
    assert resolved == tool
    assert len(tools.calls) == 2
    assert len(tools.stream_calls) == 1
    assert result.success is True
    assert result.data == {"fake": True, "arguments": {"query": "policy"}}
    assert compatibility_result.data == {"fake": True, "arguments": {"query": "policy"}}
    assert [event.type for event in stream_events] == ["started", "delta", "completed"]
    assert health["tools_enabled"] == 1
    assert capabilities["available_logical_tools"][0]["name"] == "documents.search"


async def test_fake_state_and_trace_store_record_in_memory() -> None:
    state = FakeWorkflowStateStore()
    trace = FakeTraceStore()

    await state.save("session_1", {"step": "agent"})
    loaded = await state.load("session_1")
    await state.reset("session_1")

    event = TraceEvent(
        trace_id="trace_1",
        session_id="session_1",
        event_type="agent_started",
        component="agent.fake_agent",
        timestamp=datetime.now(UTC),
    )
    await trace.record_event(event)

    assert loaded.state == {"step": "agent"}
    assert loaded.version == 1
    assert loaded.found is True
    assert "session_1" not in state.states
    assert trace.events == [event]


async def test_fake_llm_gateway_exposes_stream_health_and_profiles() -> None:
    gateway = FakeLLMGateway(response_text="streamed answer")
    context = build_context()
    request = LLMRequest(
        component="agent.fake_gateway",
        messages=[LLMMessage(role="user", content="hello")],
    )

    events = [event async for event in gateway.stream(request, context)]
    health = await gateway.health()
    profiles = await gateway.list_profiles()

    assert [event.type for event in events] == ["started", "delta", "completed"]
    assert events[1].text == "streamed answer"
    assert health.status == "ok"
    assert health.default_profile == "fake_profile"
    assert profiles[0].name == "fake_profile"
    assert profiles[0].metadata == {"source": "fake"}


async def test_fake_policy_service_can_allow_and_deny() -> None:
    allowed_policy = FakePolicyService(allow=True)
    denied_policy = FakePolicyService(allow=False)
    context = build_context()
    request = PolicyRequest(action="tool.execute", component="agent.fake_agent")

    allowed = await allowed_policy.evaluate(request, context)

    assert allowed.allowed is True

    with pytest.raises(Exception, match="Denied by fake policy"):
        await denied_policy.require_allowed(request, context)


async def test_fake_configuration_loader_returns_fake_view() -> None:
    loader = FakeConfigurationLoader({"llm": {"default_profile": "fast"}})

    view = await loader.load()

    assert loader.load_calls == 1
    assert view.get("llm.default_profile") == "fast"
    assert view.section("llm") == {"default_profile": "fast"}