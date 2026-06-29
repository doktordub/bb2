from __future__ import annotations

import pytest

from app.api.request_context import ApiRequestContext
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
from app.session.mapping import (
    build_core_request_context,
    build_session_chat_request,
    build_session_request_context,
)
from app.session.service import DefaultSessionService
from app.testing.fakes.fake_config import FakeConfigurationView
from app.testing.fakes.fake_orchestration_runtime import FakeOrchestrationRuntime
from app.testing.fakes.fake_session_id_provider import FakeSessionIdProvider
from app.testing.fakes.fake_state import FakeWorkflowStateStore
from app.testing.fakes.fake_trace import FakeTraceStore
from app.testing.fakes.fake_trace_recorder import build_fake_trace_recorder


def build_api_context() -> ApiRequestContext:
    return ApiRequestContext(
        trace_id="trace-session-map-0001",
        request_id="request-session-map-0001",
        user_id="local_user",
        user_id_hash="user_hash_123",
        client_host="127.0.0.1",
        user_agent="pytest",
        path="/chat",
        method="POST",
        headers_safe={"x-trace-id": "trace-session-map-0001"},
        metadata={"auth_mode": "local", "trace_id": "trace-session-map-0001"},
    )
def test_build_request_context_maps_api_and_chat_metadata() -> None:
    api_context = build_api_context()
    request_context = build_core_request_context(
        request=build_session_chat_request(
            message="hello there",
            session_id="session_123",
            usecase="support_chat",
            metadata={"client": "web", "timezone": "UTC"},
        ),
        context=build_session_request_context(
            trace_id=api_context.trace_id,
            request_id=api_context.request_id,
            user_id=api_context.user_id,
            user_id_hash=api_context.user_id_hash,
            client_host=api_context.client_host,
            user_agent=api_context.user_agent,
            path=api_context.path,
            method=api_context.method,
            metadata=api_context.metadata,
            headers_safe=api_context.headers_safe,
        ),
        session_id="session_123",
        default_usecase="support_chat",
    )

    assert request_context.user_id == "local_user"
    assert request_context.session_id == "session_123"
    assert request_context.message == "hello there"
    assert request_context.usecase == "support_chat"
    assert request_context.trace_id == "trace-session-map-0001"
    assert request_context.metadata == {
        "auth_mode": "local",
        "trace_id": "trace-session-map-0001",
        "client": "web",
        "timezone": "UTC",
        "request_id": "request-session-map-0001",
        "path": "/chat",
        "method": "POST",
        "user_id_hash": "user_hash_123",
        "client_host": "127.0.0.1",
        "user_agent": "pytest",
        "headers_safe": {"x-trace-id": "trace-session-map-0001"},
    }


@pytest.mark.asyncio
async def test_default_session_service_persists_state_and_records_trace() -> None:
    workflow_state = FakeWorkflowStateStore()
    trace_store = FakeTraceStore()
    service = DefaultSessionService(
        config=FakeConfigurationView(
            {
                "app": {"active_usecase": "default_chat"},
                "usecases": {
                    "default_chat": {"enabled": True},
                    "support_chat": {"enabled": True},
                },
            }
        ),
        settings=SessionSettings(
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
        ),
        workflow_state=workflow_state,
        trace_recorder=build_fake_trace_recorder(store=trace_store),
        orchestrator=FakeOrchestrationRuntime(),
        id_provider=FakeSessionIdProvider(ids=["session_generated"]),
    )

    api_context = build_api_context()

    result = await service.handle_chat(
        request=build_session_chat_request(
            message="persist this",
            session_id="session_abc",
            usecase="support_chat",
            metadata={"client": "web"},
        ),
        context=build_session_request_context(
            trace_id=api_context.trace_id,
            request_id=api_context.request_id,
            user_id=api_context.user_id,
            user_id_hash=api_context.user_id_hash,
            client_host=api_context.client_host,
            user_agent=api_context.user_agent,
            path=api_context.path,
            method=api_context.method,
            metadata=api_context.metadata,
            headers_safe=api_context.headers_safe,
        ),
    )

    assert result.session_id == "session_abc"
    assert result.trace_id == "trace-session-map-0001"
    assert result.answer == "Echo: persist this"
    assert result.metadata == {
        "usecase": "support_chat",
        "message_count": 2,
        "message_count_before": 0,
    }
    assert workflow_state.load_requests == ["session_abc"]
    assert len(workflow_state.save_requests) == 1

    saved_state = workflow_state.states["session_abc"]
    assert saved_state["conversation"]["messages"] == [
        {"role": "user", "content": "persist this"},
        {
            "role": "assistant",
            "content": "Echo: persist this",
            "metadata": {
                "agent_name": "fake_session_agent",
                "strategy_name": "fake_direct_strategy",
                "llm_profile": "fake_local_profile",
            },
        },
    ]
    assert saved_state["workflow"]["current_step"] == "answered"
    assert saved_state["last_result"] == {
        "agent_name": "fake_session_agent",
        "strategy_name": "fake_direct_strategy",
        "llm_profile": "fake_local_profile",
    }
    assert saved_state["metadata"]["trace_id"] == "trace-session-map-0001"
    assert saved_state["metadata"]["request_id"] == "request-session-map-0001"
    assert saved_state["metadata"]["usecase"] == "support_chat"
    assert saved_state["metadata"]["user_id_hash"] == "user_hash_123"

    assert len(trace_store.events) == 1
    event = trace_store.events[0]
    assert event.trace_id == "trace-session-map-0001"
    assert event.session_id == "session_abc"
    assert event.resolved_event_name == "session_created"
    assert event.payload == {
        "operation": "handle_chat",
        "loaded_empty": True,
        "message_count_before": 0,
        "message_count_after": 2,
        "message_length": 12,
        "metadata_count": 1,
    }