from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.tools import ToolScopes
from app.policy.settings import PolicyProfileSettings, PolicyToolSettings
from app.policy.tool_policy import build_tool_policy_request, evaluate_tool_request
from app.testing.fakes import FakeConfigurationView


def _build_context() -> OrchestrationContext:
    return cast(
        OrchestrationContext,
        SimpleNamespace(
            request=RequestContext(
                user_id="user-1",
                session_id="session-1",
                message="run tool",
                usecase="default_chat",
                trace_id="trace-1",
            ),
            runtime_metadata={"strategy_name": "direct_agent", "agent_name": "support_agent"},
            config=FakeConfigurationView({}),
        ),
    )


def test_build_tool_policy_request_includes_risk_and_idempotency_metadata() -> None:
    request = build_tool_policy_request(
        action="tool.execute",
        component="app.tools.gateway",
        tool_name="notes.write",
        scopes=ToolScopes(project_id="project-1"),
        context=_build_context(),
        tool_known=True,
        tool_enabled=True,
        safety_level="write",
        approval_required=False,
        supports_streaming=False,
        allowed_usecases=("default_chat",),
        allowed_agents=("support_agent",),
        allowed_strategies=("direct_agent",),
        idempotency_key_present=True,
    )

    assert request.evaluation is not None
    assert request.evaluation.risk_level == "write"
    assert request.metadata["idempotency_key_present"] is True


@pytest.mark.asyncio
async def test_tool_policy_requires_approval_for_write_tools_without_idempotency_key() -> None:
    context = _build_context()
    profile = PolicyProfileSettings(
        name="default",
        allow_write_tools=True,
        tools=PolicyToolSettings(allow_write_tools=True),
    )
    request = build_tool_policy_request(
        action="tool.execute",
        component="app.tools.gateway",
        tool_name="notes.write",
        scopes=ToolScopes(project_id="project-1"),
        context=context,
        tool_known=True,
        tool_enabled=True,
        safety_level="write",
        approval_required=False,
        supports_streaming=False,
        allowed_usecases=("default_chat",),
        allowed_agents=("support_agent",),
        allowed_strategies=("direct_agent",),
        idempotency_key_present=False,
    )

    decision = await evaluate_tool_request(request, context, profile)

    assert decision is not None
    assert decision.decision == "approval_required"
    assert decision.reason_code == "policy.tool.approval_required"


@pytest.mark.asyncio
async def test_tool_policy_denies_raw_mcp_prefixed_name() -> None:
    context = _build_context()
    request = build_tool_policy_request(
        action="tool.execute",
        component="app.tools.gateway",
        tool_name="mcp:documents.search",
        scopes=ToolScopes(project_id="project-1"),
        context=context,
        tool_known=True,
        tool_enabled=True,
        safety_level="read_only",
        approval_required=False,
        supports_streaming=True,
        allowed_usecases=("default_chat",),
        allowed_agents=("support_agent",),
        allowed_strategies=("direct_agent",),
    )

    decision = await evaluate_tool_request(
        request,
        context,
        PolicyProfileSettings(name="default"),
    )

    assert decision is not None
    assert decision.decision == "deny"
    assert decision.reason_code == "policy.tool.raw_name_denied"