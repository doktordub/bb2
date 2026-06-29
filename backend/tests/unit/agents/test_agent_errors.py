from __future__ import annotations

import asyncio

from app.agents.errors import (
    AgentCancelledError,
    AgentErrorDetail,
    AgentLLMError,
    AgentPolicyDeniedError,
    agent_error_from_detail,
    normalize_agent_error,
)
from app.contracts.errors import LLMGatewayError, PolicyDeniedError


def test_agent_error_detail_sanitizes_message_and_metadata() -> None:
    detail = AgentErrorDetail(
        code="agent_failure",
        message='Traceback: File "hidden.py"',
        retryable=False,
        metadata={"safe": "ok", "raw_prompt": "blocked"},
    )

    assert detail.code == "agent_failure"
    assert detail.message == "The agent request failed."
    assert detail.metadata == {"safe": "ok"}


def test_normalize_agent_error_maps_policy_and_gateway_failures() -> None:
    assert isinstance(normalize_agent_error(PolicyDeniedError("denied")), AgentPolicyDeniedError)

    llm_error = normalize_agent_error(LLMGatewayError("provider timeout"))
    assert isinstance(llm_error, AgentLLMError)
    assert llm_error.retryable is True


def test_agent_error_detail_round_trip_restores_specific_error_type() -> None:
    detail = AgentLLMError("Retry later.", retryable=True, metadata={"safe": "ok"}).to_detail()

    rebuilt = agent_error_from_detail(detail)

    assert isinstance(rebuilt, AgentLLMError)
    assert rebuilt.message == "Retry later."
    assert rebuilt.retryable is True
    assert rebuilt.metadata == {"safe": "ok"}


def test_normalize_agent_error_maps_cancellation() -> None:
    normalized = normalize_agent_error(asyncio.CancelledError())

    assert isinstance(normalized, AgentCancelledError)
    assert normalized.code == "agent_cancelled"
    assert normalized.retryable is False