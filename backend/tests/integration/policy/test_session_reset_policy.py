from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.config.view import (
    SessionConcurrencySettings,
    SessionDefaultsSettings,
    SessionHistorySettings,
    SessionIdentifierSettings,
    SessionLifecycleSettings,
    SessionSettings,
    SessionStateSettings,
    SessionTracingSettings,
)
from app.contracts.errors import PolicyDeniedError
from app.policy.service import DefaultPolicyService
from app.session.mapping import build_session_request_context
from app.session.service import DefaultSessionService
from app.testing.fakes import FakeConfigurationView, FakeOrchestrationRuntime, FakeWorkflowStateStore
from app.testing.fakes.fake_clock import FakeClock
from app.testing.fakes.fake_trace import FakeTraceStore
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


def _settings() -> SessionSettings:
    return SessionSettings(
        enabled=True,
        identifiers=SessionIdentifierSettings(prefix="session", accept_client_session_id=True, generate_when_missing=True, max_length=128, allowed_pattern="^[A-Za-z0-9_.:-]{3,128}$"),
        defaults=SessionDefaultsSettings(default_user_id="local_user", default_usecase="default_chat", default_history_limit=50, max_history_limit=200, timezone_metadata_key="timezone"),
        lifecycle=SessionLifecycleSettings(create_on_first_chat=True, resume_existing_sessions=True, reject_unknown_client_session_id=False, update_last_seen_on_load=True, save_after_failed_orchestration=True, save_after_cancelled_stream=True),
        concurrency=SessionConcurrencySettings(mode="optimistic_version", conflict_policy="reject", max_retries=1),
        state=SessionStateSettings(save_on_chat_completion=True, save_on_stream_completion=True, save_on_stream_cancellation=True, save_on_stream_failure=True, save_each_stream_delta=False),
        history=SessionHistorySettings(enabled=True, include_tool_summaries=False, include_system_messages=False, include_metadata=True, max_message_chars=4000, redaction_enabled=True),
        tracing=SessionTracingSettings(record_session_created=True, record_session_resumed=True, record_session_reset=True, record_state_loaded=True, record_state_saved=True, record_history_returned=True, record_stream_lifecycle=True),
    )


def _context():
    return build_session_request_context(
        trace_id="trace-session-reset-policy-1",
        request_id="request-session-reset-policy-1",
        user_id="local_user",
        user_id_hash="user_hash_123",
        client_host="127.0.0.1",
        user_agent="pytest",
        path="/sessions/session_policy_1/reset",
        method="POST",
        metadata={"auth_mode": "local"},
        headers_safe={"x-trace-id": "trace-session-reset-policy-1"},
    )


@pytest.mark.asyncio
async def test_session_reset_denied_by_policy_stops_before_reset() -> None:
    workflow_state = FakeWorkflowStateStore()
    workflow_state.states["session_policy_1"] = {
        "conversation": {"messages": [{"role": "user", "content": "hello"}]},
        "workflow": {"current_step": "answered"},
        "metadata": {"user_id": "other_user", "user_id_hash": "other_hash", "usecase": "default_chat"},
    }
    workflow_state.versions["session_policy_1"] = 1
    service = DefaultSessionService(
        config=FakeConfigurationView({"usecases": {"default_chat": {"enabled": True}}}),
        settings=_settings(),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=FakeTraceStore()),
        orchestrator=FakeOrchestrationRuntime(),
        policy_service=DefaultPolicyService(FakeConfigurationView({"policy": {"default_profile": "default"}})),
        clock=FakeClock([datetime(2026, 6, 27, 17, 0, tzinfo=UTC)]),
    )

    with pytest.raises(PolicyDeniedError):
        await service.reset_session(session_id="session_policy_1", reason="user_requested", context=_context())

    assert workflow_state.reset_calls == []