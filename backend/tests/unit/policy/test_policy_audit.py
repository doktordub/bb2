from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.policy import PolicyDecision, PolicyRequest
from app.policy.audit import PolicyAuditRecorder
from app.policy.settings import PolicyAuditSettings
from app.testing.fakes import (
    FakeConfigurationView,
    FakeLLMGateway,
    FakeMemoryGateway,
    FakeToolGateway,
    FakeTraceStore,
    FakeWorkflowStateStore,
)


def _build_context() -> OrchestrationContext:
    return cast(
        OrchestrationContext,
        OrchestrationContext(
            request=RequestContext(
                user_id="user-1",
                session_id="session-1",
                message="hello",
                usecase="default_chat",
                trace_id="trace-1",
            ),
            llm=FakeLLMGateway(),
            memory=FakeMemoryGateway(),
            state=FakeWorkflowStateStore(),
            tools=FakeToolGateway(),
            trace=FakeTraceStore(),
            policy=cast(object, SimpleNamespace()),
            config=FakeConfigurationView({}),
            runtime_metadata={"strategy_name": "direct_agent", "agent_name": "support_agent"},
        ),
    )


def test_policy_audit_records_only_safe_summary_fields() -> None:
    recorder = PolicyAuditRecorder(
        PolicyAuditSettings(
            enabled=True,
            include_reason_codes=True,
            include_actor_identifiers=False,
            include_resource_names=True,
        )
    )
    request = PolicyRequest(
        action="tool.execute",
        component="app.tools.gateway",
        resource="billing.charge",
        scope={"user_id": "user-1", "session_id": "session-1", "usecase_name": "default_chat"},
        metadata={"tool_name": "billing.charge", "authorization": "Bearer secret-token"},
    )
    decision = PolicyDecision.approval_required(
        reason_code="policy.tool.approval_required",
        metadata={"policy_profile": "default", "rule": "tool_access", "tool_arguments": {"amount": 42}},
    )

    event = recorder.record(request, _build_context(), decision=decision)

    assert event is not None
    assert event.decision == "approval_required"
    assert event.reason_code == "policy.tool.approval_required"
    assert event.resource == "billing.charge"
    assert event.actor_hash is None
    snapshot = recorder.snapshot()
    assert snapshot["event_count"] == 1
    assert snapshot["decision_counts"] == {"allow": 0, "deny": 0, "approval_required": 1}
    assert snapshot["last_event"]["resource"] == "billing.charge"
    assert "tool_arguments" not in snapshot["last_event"]