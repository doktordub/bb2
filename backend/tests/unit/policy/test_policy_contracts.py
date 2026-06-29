from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.contracts.context import OrchestrationContext
from app.contracts.errors import PolicyDeniedError
from app.contracts.policy import (
    PolicyActor,
    PolicyDecision,
    PolicyEvaluationContext,
    PolicyObligation,
    PolicyRequest,
)
from app.testing.fakes.fake_policy import FakePolicyService


def test_policy_request_resolves_actor_scope_and_evaluation_from_legacy_fields() -> None:
    request = PolicyRequest(
        action="tool.execute",
        component="app.tools.gateway",
        resource="documents.search",
        scope={
            "project_id": "project-1",
            "user_id": "user-1",
            "session_id": "session-1",
            "usecase": "default_chat",
            "strategy_name": "direct_agent",
            "agent_name": "support_agent",
        },
        metadata={
            "trace_id": "trace-1",
            "request_id": "request-1",
            "risk_level": "read_only",
            "roles": ["member"],
            "actor_attributes": {"origin": "unit-test"},
            "tags": ["tools", "policy"],
        },
    )

    assert request.resolved_actor() == PolicyActor(
        actor_type="user",
        actor_id="user-1",
        user_id="user-1",
        tenant_id=None,
        session_id="session-1",
        roles=("member",),
        attributes={"origin": "unit-test"},
    )
    assert request.resolved_scope().project_id == "project-1"
    assert request.resolved_scope().usecase_name == "default_chat"
    assert request.resolved_evaluation() == PolicyEvaluationContext(
        trace_id="trace-1",
        request_id="request-1",
        usecase_name="default_chat",
        strategy_name="direct_agent",
        agent_name="support_agent",
        llm_profile=None,
        tool_name="documents.search",
        risk_level="read_only",
        exposure_level="summary",
        tags=("tools", "policy"),
        metadata={
            "trace_id": "trace-1",
            "request_id": "request-1",
            "risk_level": "read_only",
            "roles": ["member"],
            "actor_attributes": {"origin": "unit-test"},
            "tags": ["tools", "policy"],
        },
    )


def test_policy_decision_helpers_normalize_legacy_flags() -> None:
    allowed = PolicyDecision.allow(metadata={"path": "allow"})
    denied = PolicyDecision.deny(reason="Denied", reason_code="policy.denied")
    approval = PolicyDecision.approval_required(
        reason="Approval required",
        reason_code="policy.approval_required",
        obligations=(PolicyObligation(kind="require_approval", target="tool.execute"),),
    )

    assert allowed.allowed is True
    assert allowed.decision == "allow"
    assert allowed.is_allowed is True
    assert denied.allowed is False
    assert denied.requires_approval is False
    assert denied.decision == "deny"
    assert denied.safe_reason == "Denied"
    assert approval.allowed is False
    assert approval.requires_approval is True
    assert approval.decision == "approval_required"
    assert approval.is_approval_required is True
    assert approval.obligations[0].kind == "require_approval"


async def test_fake_policy_service_returns_structured_approval_required_decision() -> None:
    service = FakePolicyService(approval_required_actions={"tool.execute"})
    request = PolicyRequest(
        action="tool.execute",
        component="app.tools.gateway",
        resource="documents.search",
        scope={"user_id": "user-1", "project_id": "project-1"},
    )

    decision = await service.evaluate(
        request,
        cast(OrchestrationContext, SimpleNamespace()),
    )

    assert decision.decision == "approval_required"
    assert decision.requires_approval is True
    assert decision.reason_code == "fake.approval_required"
    assert decision.scope is not None
    assert decision.scope.project_id == "project-1"


async def test_fake_policy_service_require_allowed_raises_policy_denied() -> None:
    service = FakePolicyService(allow=False, deny_reason="No access")
    request = PolicyRequest(action="memory.search", component="app.memory.gateway")

    with pytest.raises(PolicyDeniedError, match="No access"):
        await service.require_allowed(
            request,
            cast(OrchestrationContext, SimpleNamespace()),
        )
