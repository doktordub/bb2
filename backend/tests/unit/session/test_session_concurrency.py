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
from app.persistence.errors import WorkflowStateConflictError
from app.session.concurrency import map_conflict_error
from app.session.errors import SessionConflictError
from app.session.mapping import build_session_chat_request, build_session_request_context
from app.session.service import DefaultSessionService
from app.testing.fakes.fake_clock import FakeClock
from app.testing.fakes.fake_config import FakeConfigurationView
from app.testing.fakes.fake_orchestration_runtime import FakeOrchestrationRuntime
from app.testing.fakes.fake_state import FakeWorkflowStateStore
from app.testing.fakes.fake_trace import FakeTraceStore
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


def _build_settings() -> SessionSettings:
    return SessionSettings(
        enabled=True,
        identifiers=SessionIdentifierSettings(
            prefix="session",
            accept_client_session_id=True,
            generate_when_missing=True,
            max_length=128,
            allowed_pattern="^[A-Za-z0-9_.:-]{3,128}$",
        ),
        defaults=SessionDefaultsSettings(
            default_user_id="local_user",
            default_usecase="default_chat",
            default_history_limit=50,
            max_history_limit=200,
            timezone_metadata_key="timezone",
        ),
        lifecycle=SessionLifecycleSettings(
            create_on_first_chat=True,
            resume_existing_sessions=True,
            reject_unknown_client_session_id=False,
            update_last_seen_on_load=True,
            save_after_failed_orchestration=True,
            save_after_cancelled_stream=True,
        ),
        concurrency=SessionConcurrencySettings(
            mode="optimistic_version",
            conflict_policy="reject",
            max_retries=1,
        ),
        state=SessionStateSettings(
            save_on_chat_completion=True,
            save_on_stream_completion=True,
            save_on_stream_cancellation=True,
            save_on_stream_failure=True,
            save_each_stream_delta=False,
        ),
        history=SessionHistorySettings(
            enabled=False,
            include_tool_summaries=False,
            include_system_messages=False,
            include_metadata=True,
            max_message_chars=4000,
            redaction_enabled=True,
        ),
        tracing=SessionTracingSettings(
            record_session_created=True,
            record_session_resumed=True,
            record_session_reset=True,
            record_state_loaded=True,
            record_state_saved=True,
            record_history_returned=True,
            record_stream_lifecycle=True,
        ),
    )
def _build_context():
    return build_session_request_context(
        trace_id="trace-session-conflict-0001",
        request_id="request-session-conflict-0001",
        user_id="local_user",
        user_id_hash="user_hash_123",
        client_host="127.0.0.1",
        user_agent="pytest",
        path="/chat/stream",
        method="POST",
        metadata={"auth_mode": "local"},
        headers_safe={"x-trace-id": "trace-session-conflict-0001"},
    )


@pytest.mark.asyncio
async def test_stream_chat_raises_session_conflict_when_final_save_conflicts() -> None:
    workflow_state = FakeWorkflowStateStore()
    workflow_state.queue_conflict("session_stream_conflict")
    service = DefaultSessionService(
        config=FakeConfigurationView({"usecases": {"default_chat": {"enabled": True}}}),
        settings=_build_settings(),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=FakeTraceStore()),
        orchestrator=FakeOrchestrationRuntime(),
        clock=FakeClock(
            [
                datetime(2026, 6, 27, 16, 30, tzinfo=UTC),
                datetime(2026, 6, 27, 16, 30, 1, tzinfo=UTC),
            ]
        ),
    )

    received_event_types: list[str] = []
    with pytest.raises(SessionConflictError, match="stream could be saved|stream could be finalized"):
        async for event in service.stream_chat(
            request=build_session_chat_request(
                message="conflict me",
                session_id="session_stream_conflict",
                usecase=None,
            ),
            context=_build_context(),
        ):
            received_event_types.append(event.event_type)

    assert received_event_types == [
        "response.started",
        "response.delta",
        "response.delta",
        "response.metadata",
    ]
    assert len(workflow_state.save_calls) == 0


def test_conflict_helper_returns_reset_specific_message() -> None:
    error = map_conflict_error(
        operation="reset",
        settings=_build_settings().concurrency,
        error=WorkflowStateConflictError("conflict"),
    )

    assert isinstance(error, SessionConflictError)
    assert error.message == "The session changed during reset."
    assert error.retryable is True
