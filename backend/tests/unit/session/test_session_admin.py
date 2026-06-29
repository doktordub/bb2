from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.config.view import (
    SessionConcurrencySettings,
    SessionDefaultsSettings,
    SessionHistorySettings,
    SessionIdentifierSettings,
    SessionLifecycleSettings,
    SessionManagementSettings,
    SessionSettings,
    SessionStateSettings,
    SessionTracingSettings,
)
from app.session.errors import SessionDeleteDisabledError, SessionListDisabledError, SessionNotFoundError
from app.session.mapping import build_session_request_context
from app.session.service import DefaultSessionService
from app.testing.fakes.fake_clock import FakeClock
from app.testing.fakes.fake_config import FakeConfigurationView
from app.testing.fakes.fake_orchestration_runtime import FakeOrchestrationRuntime
from app.testing.fakes.fake_policy import FakePolicyService
from app.testing.fakes.fake_state import FakeWorkflowStateStore
from app.testing.fakes.fake_trace import FakeTraceStore
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


def _build_settings(*, list_enabled: bool = True, delete_enabled: bool = True) -> SessionSettings:
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
        management=SessionManagementSettings(
            list_enabled=list_enabled,
            delete_enabled=delete_enabled,
            default_list_limit=2,
            max_list_limit=3,
        ),
    )


def _build_context():
    return build_session_request_context(
        trace_id="trace-session-admin-0001",
        request_id="request-session-admin-0001",
        user_id="local_user",
        user_id_hash="user_hash_123",
        client_host="127.0.0.1",
        user_agent="pytest",
        path="/sessions",
        method="GET",
        metadata={"auth_mode": "local"},
        headers_safe={"x-trace-id": "trace-session-admin-0001"},
    )


def _build_service(*, list_enabled: bool = True, delete_enabled: bool = True) -> tuple[DefaultSessionService, FakeWorkflowStateStore]:
    workflow_state = FakeWorkflowStateStore()
    trace_store = FakeTraceStore()
    service = DefaultSessionService(
        config=FakeConfigurationView({"usecases": {"default_chat": {"enabled": True}}}),
        settings=_build_settings(list_enabled=list_enabled, delete_enabled=delete_enabled),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=trace_store),
        orchestrator=FakeOrchestrationRuntime(),
        policy_service=FakePolicyService(),
        clock=FakeClock([datetime(2026, 6, 28, 17, 0, tzinfo=UTC)]),
    )
    return service, workflow_state


@pytest.mark.asyncio
async def test_list_sessions_returns_bounded_safe_projection() -> None:
    service, workflow_state = _build_service()
    await workflow_state.save(
        "session_a",
        {"conversation": {"messages": [{"role": "user", "content": "hello"}]}},
        metadata={"usecase": "default_chat"},
    )
    await workflow_state.save(
        "session_b",
        {
            "conversation": {
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "yo"},
                ]
            }
        },
        metadata={"usecase": "support"},
    )

    result = await service.list_sessions(limit=None, context=_build_context())

    assert result.trace_id == "trace-session-admin-0001"
    assert result.limit == 2
    assert len(result.sessions) == 2
    assert {item.session_id for item in result.sessions} == {"session_a", "session_b"}
    assert result.metadata == {"limit": 2, "returned_count": 2, "has_more": False}


@pytest.mark.asyncio
async def test_list_sessions_raises_when_disabled() -> None:
    service, _ = _build_service(list_enabled=False)

    with pytest.raises(SessionListDisabledError):
        await service.list_sessions(limit=1, context=_build_context())


@pytest.mark.asyncio
async def test_delete_session_removes_known_session() -> None:
    service, workflow_state = _build_service()
    await workflow_state.save(
        "session_delete_1",
        {"conversation": {"messages": [{"role": "user", "content": "hello"}]}},
        metadata={"usecase": "default_chat"},
    )

    result = await service.delete_session(session_id="session_delete_1", context=_build_context())

    assert result.deleted is True
    assert result.session_id == "session_delete_1"
    assert "session_delete_1" not in workflow_state.states


@pytest.mark.asyncio
async def test_delete_session_raises_not_found_for_unknown_session() -> None:
    service, _ = _build_service()

    with pytest.raises(SessionNotFoundError):
        await service.delete_session(session_id="missing_session", context=_build_context())


@pytest.mark.asyncio
async def test_delete_session_raises_when_disabled() -> None:
    service, _ = _build_service(delete_enabled=False)

    with pytest.raises(SessionDeleteDisabledError):
        await service.delete_session(session_id="session_delete_1", context=_build_context())