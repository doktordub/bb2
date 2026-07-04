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
from app.persistence.sqlite_workflow_state_store import SqliteWorkflowStateStore
from app.session.mapping import build_session_chat_request, build_session_request_context
from app.session.service import DefaultSessionService
from app.testing.fakes.fake_clock import FakeClock
from app.testing.fakes.fake_config import FakeConfigurationView
from app.testing.fakes.fake_orchestration_runtime import FakeOrchestrationRuntime
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
def _build_context(trace_id: str):
    return build_session_request_context(
        trace_id=trace_id,
        request_id=trace_id,
        user_id="local_user",
        user_id_hash="user_hash_123",
        client_host="127.0.0.1",
        user_agent="pytest",
        path="/chat/stream",
        method="POST",
        metadata={"auth_mode": "local"},
        headers_safe={"x-trace-id": trace_id},
    )


@pytest.mark.asyncio
async def test_default_session_service_streaming_finalizes_once_with_sqlite_store(tmp_path) -> None:
    workflow_state = SqliteWorkflowStateStore(tmp_path / "workflow_state.db")
    await workflow_state.initialize()

    service = DefaultSessionService(
        config=FakeConfigurationView({"usecases": {"default_chat": {"enabled": True}}}),
        settings=_build_settings(),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=FakeTraceStore()),
        orchestrator=FakeOrchestrationRuntime(),
        clock=FakeClock(
            [
                datetime(2026, 6, 27, 18, 0, tzinfo=UTC),
                datetime(2026, 6, 27, 18, 0, 1, tzinfo=UTC),
            ]
        ),
    )

    events = [
        event
        async for event in service.stream_chat(
            request=build_session_chat_request(
                message="sqlite stream",
                session_id="session_sqlite_stream_1",
                usecase=None,
            ),
            context=_build_context("trace-sqlite-stream-0001"),
        )
    ]

    assert [event.event_type for event in events] == [
        "response.started",
        "response.delta",
        "response.delta",
        "response.metadata",
        "response.completed",
    ]

    loaded = await workflow_state.load("session_sqlite_stream_1")
    assert loaded.version == 1
    assert loaded.state["conversation"]["messages"] == [
        {
            "role": "user",
            "content": "sqlite stream",
            "created_at": "2026-06-27T18:00:00+00:00",
            "metadata": {
                "usecase": "default_chat",
                "request_id": "trace-sqlite-stream-0001",
                "turn_id": "trace-sqlite-stream-0001",
                "trace_id": "trace-sqlite-stream-0001",
            },
        },
        {
            "role": "assistant",
            "content": "Echo: sqlite stream",
            "created_at": "2026-06-27T18:00:01+00:00",
            "metadata": {
                "agent_name": "fake_session_agent",
                "strategy_name": "fake_direct_strategy",
                "llm_profile": "fake_local_profile",
                "request_id": "trace-sqlite-stream-0001",
                "turn_id": "trace-sqlite-stream-0001",
                "trace_id": "trace-sqlite-stream-0001",
                "usecase": "default_chat",
            },
        },
    ]
