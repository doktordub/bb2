from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.contracts.context import OrchestrationContext, RequestContext
from app.contracts.policy import PolicyRequest
from app.policy.session_policy import build_session_policy_request, evaluate_session_access
from app.policy.settings import PolicyProfileSettings
from app.testing.fakes import FakeConfigurationView


def _build_context() -> OrchestrationContext:
    return cast(
        OrchestrationContext,
        SimpleNamespace(
            request=RequestContext(
                user_id="local_user",
                session_id="session-1",
                message="hello",
                usecase="default_chat",
                trace_id="trace-1",
            ),
            runtime_metadata={"usecase_name": "default_chat", "session_id": "session-1"},
            config=FakeConfigurationView({}),
        ),
    )


@pytest.mark.asyncio
async def test_session_policy_allows_owner_reset_request() -> None:
    request = build_session_policy_request(
        action="session.reset",
        component="session.service",
        session_id="session-1",
        user_id="local_user",
        user_id_hash="hash-1",
        usecase_name="default_chat",
        owner_user_id="local_user",
        owner_user_id_hash="hash-1",
    )

    decision = await evaluate_session_access(
        request,
        _build_context(),
        PolicyProfileSettings(name="default"),
        FakeConfigurationView({}),
    )

    assert decision is not None
    assert decision.decision == "allow"
    assert decision.reason_code == "policy.session.reset_allowed"


@pytest.mark.asyncio
async def test_session_policy_denies_owner_mismatch_for_history() -> None:
    request = build_session_policy_request(
        action="session.read_history",
        component="session.service",
        session_id="session-1",
        user_id="local_user",
        user_id_hash="hash-1",
        usecase_name="default_chat",
        owner_user_id="other_user",
    )

    decision = await evaluate_session_access(
        request,
        _build_context(),
        PolicyProfileSettings(name="default"),
        FakeConfigurationView({}),
    )

    assert decision is not None
    assert decision.decision == "deny"
    assert decision.reason_code == "policy.session.owner_mismatch"


@pytest.mark.asyncio
async def test_session_policy_denies_missing_session_identifier() -> None:
    request = PolicyRequest(
        action="session.reset",
        component="session.service",
        metadata={"actor_type": "user", "actor_id": "local_user"},
    )

    decision = await evaluate_session_access(
        request,
        _build_context(),
        PolicyProfileSettings(name="default"),
        FakeConfigurationView({}),
    )

    assert decision is not None
    assert decision.decision == "deny"
    assert decision.reason_code == "policy.session.missing_session_id"