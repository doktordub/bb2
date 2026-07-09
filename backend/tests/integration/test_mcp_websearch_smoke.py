from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config.loader import load_validated_config
from app.config.view import ValidatedConfigurationView
from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.tools import ToolExecutionRequest, ToolScopes
from app.policy.service import DefaultPolicyService
from app.testing.fakes import (
    FakeLLMGateway,
    FakeMemoryGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)
from app.tools.factory import build_tooling_runtime, initialize_tooling_runtime


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("BB2_RUN_LOCAL_MCP_TESTS") != "1",
    reason="Local MCP smoke tests are opt-in.",
)
async def test_local_mcp_websearch_discovery_smoke() -> None:
    config = ValidatedConfigurationView(
        load_validated_config(
            Path("tests/fixtures/config/tooling_local_mcp_websearch.yaml")
        ).model_dump(mode="python")
    )
    runtime = build_tooling_runtime(config)
    await initialize_tooling_runtime(runtime)

    health = await runtime.gateway.health()
    capabilities = await runtime.gateway.capabilities()
    discovered_tools = await runtime.mcp_adapter.list_tools()

    assert health.status == "ok"
    assert health.mcp_status == "ok"
    assert health.tools_discovered >= 1
    assert any(tool.name == "websearch.search" for tool in discovered_tools)
    assert any(tool.name == "websearch.search" for tool in capabilities.available_logical_tools)

    registry_entry = runtime.registry.resolve_entry("websearch.search")
    assert registry_entry.definition.mcp_tool_name == "websearch.search"
    assert registry_entry.metadata["mcp_available"] is True


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.external_network
@pytest.mark.skipif(
    os.getenv("BB2_RUN_EXTERNAL_MCP_WEBSEARCH_TESTS") != "1",
    reason="External-network MCP websearch smoke tests are opt-in.",
)
async def test_local_mcp_websearch_executes_through_tool_gateway() -> None:
    config = ValidatedConfigurationView(
        load_validated_config(
            Path("tests/fixtures/config/tooling_local_mcp_websearch.yaml")
        ).model_dump(mode="python")
    )
    runtime = build_tooling_runtime(config)
    await initialize_tooling_runtime(runtime)

    context = OrchestrationContext(
        request=RequestContext(
            user_id="user_smoke_1",
            session_id="session_mcp_websearch_smoke_1",
            message="search the web",
            usecase="default_chat",
            trace_id="trace-backend-websearch-smoke-0001",
        ),
        llm=FakeLLMGateway(),
        memory=FakeMemoryGateway(),
        state=FakeWorkflowStateStore(),
        tools=runtime.gateway,
        trace=FakeTraceStore(),
        policy=DefaultPolicyService(config),
        config=config,
        runtime_metadata={
            "agent_name": "support_agent",
            "strategy_name": "direct_agent",
        },
    )

    result = await runtime.gateway.execute(
        ToolExecutionRequest(
            tool_name="websearch.search",
            arguments={
                "query": "Python FastMCP",
                "max_results": 2,
            },
            scopes=ToolScopes(project_id="bb2"),
        ),
        context,
    )

    assert result.success is True
    assert result.tool_name == "websearch.search"
    assert isinstance(result.structured_content, dict)
    assert result.structured_content["result_count"] <= 2
    assert len(result.structured_content["results"]) <= 2
    if result.structured_content["ok"] is True:
        assert result.structured_content["results"]
        for item in result.structured_content["results"]:
            assert set(item) >= {"rank", "title", "url", "snippet", "source"}
            assert all(item[field] for field in ("title", "url", "source"))
        return

    assert result.structured_content["results"] == []
    assert result.structured_content["error"] == {
        "code": "provider_unavailable",
        "message": "Web search provider is unavailable.",
        "retryable": True,
    }