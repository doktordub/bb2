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
from app.session.errors import SessionHistoryDisabledError
from app.session.mapping import build_session_request_context
from app.session.service import DefaultSessionService
from app.testing.fakes.fake_clock import FakeClock
from app.testing.fakes.fake_config import FakeConfigurationView
from app.testing.fakes.fake_orchestration_runtime import FakeOrchestrationRuntime
from app.testing.fakes.fake_policy import FakePolicyService
from app.testing.fakes.fake_state import FakeWorkflowStateStore
from app.testing.fakes.fake_trace import FakeTraceStore
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


def _build_settings(*, history_enabled: bool) -> SessionSettings:
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
            enabled=history_enabled,
            include_tool_summaries=False,
            include_system_messages=False,
            include_metadata=True,
            max_message_chars=8,
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
        trace_id="trace-session-history-0001",
        request_id="request-session-history-0001",
        user_id="local_user",
        user_id_hash="user_hash_123",
        client_host="127.0.0.1",
        user_agent="pytest",
        path="/sessions/session_history_1/history",
        method="GET",
        metadata={"auth_mode": "local"},
        headers_safe={"x-trace-id": "trace-session-history-0001"},
    )


@pytest.mark.asyncio
async def test_get_history_returns_bounded_safe_projection() -> None:
    workflow_state = FakeWorkflowStateStore()
    workflow_state.states["session_history_1"] = {
        "conversation": {
            "messages": [
                {"role": "system", "content": "hidden system directive"},
                {"role": "user", "content": "first turn", "metadata": {"token": "secret"}},
                {"role": "assistant", "content": "very long assistant answer", "metadata": {"api_key": "secret"}},
                {"role": "tool", "content": "raw tool payload"},
                {"role": "user", "content": "last turn"},
            ]
        },
        "workflow": {"current_step": "answered", "scratch": {"thought": "hidden"}},
        "metadata": {"loaded_empty": False},
    }
    workflow_state.versions["session_history_1"] = 3
    trace_store = FakeTraceStore()
    service = DefaultSessionService(
        config=FakeConfigurationView({"usecases": {"default_chat": {"enabled": True}}}),
        settings=_build_settings(history_enabled=True),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=trace_store),
        orchestrator=FakeOrchestrationRuntime(),
        policy_service=FakePolicyService(),
        clock=FakeClock([datetime(2026, 6, 27, 17, 30, tzinfo=UTC)]),
    )

    result = await service.get_history(
        session_id="session_history_1",
        limit=2,
        context=_build_context(),
    )

    assert result.session_id == "session_history_1"
    assert result.truncated is True
    assert result.metadata == {"limit": 2, "returned_count": 2}
    assert [(item.role, item.content, item.metadata) for item in result.messages] == [
        ("assistant", "very lon", {"message_chars": 26, "content_truncated": True}),
        ("user", "last tur", {"message_chars": 9, "content_truncated": True}),
    ]
    assert [event.resolved_event_name for event in trace_store.events] == ["session_history_returned"]
    assert "hidden" not in str(trace_store.events[0].payload)


@pytest.mark.asyncio
async def test_get_history_raises_when_history_is_disabled() -> None:
    service = DefaultSessionService(
        config=FakeConfigurationView({"usecases": {"default_chat": {"enabled": True}}}),
        settings=_build_settings(history_enabled=False),
        workflow_state=FakeWorkflowStateStore(),
        trace_recorder=build_fake_trace_recorder(store=FakeTraceStore()),
        orchestrator=FakeOrchestrationRuntime(),
        policy_service=FakePolicyService(),
        clock=FakeClock([datetime(2026, 6, 27, 17, 31, tzinfo=UTC)]),
    )

    with pytest.raises(SessionHistoryDisabledError):
        await service.get_history(
            session_id="session_history_missing",
            limit=10,
            context=_build_context(),
        )
