from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.memory import MemoryScope, MemoryWrite
from app.policy.memory_policy import build_memory_policy_request, evaluate_memory_request
from app.policy.settings import PolicyMemorySettings, PolicyProfileSettings
from app.testing.fakes import FakeConfigurationView


def _build_context() -> OrchestrationContext:
    return cast(
        OrchestrationContext,
        SimpleNamespace(
            request=RequestContext(
                user_id="user-1",
                session_id="session-1",
                message="remember this",
                usecase="default_chat",
                trace_id="trace-1",
            ),
            runtime_metadata={"strategy_name": "memory_update", "agent_name": "support_agent"},
            config=FakeConfigurationView({}),
        ),
    )


def test_build_memory_policy_request_includes_scope_type_and_intent_metadata() -> None:
    context = _build_context()
    memory_write = MemoryWrite(
        text="remember me",
        scope=MemoryScope(project_id="project-1", user_id="user-1"),
        memory_type="user_fact",
        metadata={"reason": "explicit_remember_request", "source": "request_message"},
    )

    request = build_memory_policy_request(
        action="memory.upsert",
        component="app.memory.gateway",
        scope=memory_write.scope,
        context=context,
        resource=memory_write.memory_type,
        provider="fake",
        memory_write=memory_write,
    )

    assert request.evaluation is not None
    assert request.metadata["memory_scope_type"] == "project_user"
    assert request.metadata["memory_intent_explicit"] is True


@pytest.mark.asyncio
async def test_memory_policy_denies_sensitive_writes_by_default() -> None:
    context = _build_context()
    profile = PolicyProfileSettings(
        name="default",
        allow_memory_writes=True,
        memory=PolicyMemorySettings(allow_writes=True, allowed_write_scopes=("project",)),
    )
    request = build_memory_policy_request(
        action="memory.upsert",
        component="app.memory.gateway",
        scope=MemoryScope(project_id="project-1"),
        context=context,
        resource="user_fact",
        provider="fake",
        memory_write=MemoryWrite(
            text="secret",
            scope=MemoryScope(project_id="project-1"),
            memory_type="user_fact",
            metadata={"sensitivity": "sensitive"},
        ),
    )

    decision = await evaluate_memory_request(request, context, profile)

    assert decision is not None
    assert decision.decision == "deny"
    assert decision.reason_code == "policy.memory.sensitive_denied"


@pytest.mark.asyncio
async def test_memory_policy_requires_approval_for_admin_memory_operation() -> None:
    context = _build_context()
    profile = PolicyProfileSettings(
        name="default",
        allow_memory_writes=True,
        memory=PolicyMemorySettings(allow_writes=True, allowed_write_scopes=("project",)),
    )
    request = build_memory_policy_request(
        action="memory.delete_by_scope",
        component="app.memory.gateway",
        scope=MemoryScope(project_id="project-1"),
        context=context,
        provider="fake",
    )

    decision = await evaluate_memory_request(request, context, profile)

    assert decision is not None
    assert decision.decision == "approval_required"
    assert decision.reason_code == "policy.memory.approval_required"