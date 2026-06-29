from __future__ import annotations

from typing import cast

import pytest

from app.api.request_context import ApiRequestContext
from app.session.mapping import build_session_chat_request, build_session_request_context
from app.testing.fakes.fake_session_service import FakeSessionService


def build_context() -> ApiRequestContext:
    return ApiRequestContext(
        trace_id="trace_test_12345678",
        request_id="trace_test_12345678",
        user_id="local_user",
        user_id_hash="user_hash",
        client_host="127.0.0.1",
        user_agent="pytest",
        path="/chat",
        method="POST",
        headers_safe={"x-trace-id": "trace_test_12345678"},
        metadata={"auth_mode": "local"},
    )


def to_session_context():
    context = build_context()
    return build_session_request_context(
        trace_id=context.trace_id,
        request_id=context.request_id,
        user_id=context.user_id,
        user_id_hash=context.user_id_hash,
        client_host=context.client_host,
        user_agent=context.user_agent,
        path=context.path,
        method=context.method,
        metadata=context.metadata,
        headers_safe=context.headers_safe,
    )


@pytest.mark.asyncio
async def test_fake_session_service_generates_stable_session_ids() -> None:
    service = FakeSessionService()
    context = to_session_context()

    first = await service.handle_chat(
        request=build_session_chat_request(message="hello", session_id=None, usecase=None),
        context=context,
    )
    second = await service.handle_chat(
        request=build_session_chat_request(
            message="hello again",
            session_id=None,
            usecase=None,
        ),
        context=context,
    )

    assert first.session_id == "session_0001"
    assert second.session_id == "session_0002"
    assert first.answer == "Echo: hello"
    assert second.answer == "Echo: hello again"


@pytest.mark.asyncio
async def test_fake_session_service_reuses_client_session_id_and_records_context() -> None:
    service = FakeSessionService()
    context = to_session_context()

    result = await service.handle_chat(
        request=build_session_chat_request(
            message="summarize this",
            session_id="session_123",
            usecase="support_chat",
            metadata={"client": "web"},
        ),
        context=context,
    )

    assert result.session_id == "session_123"
    assert result.metadata["usecase"] == "support_chat"
    assert result.metadata["message_count"] == 2
    assert service.states["session_123"]["last_result"] == {
        "agent_name": "fake_session_agent",
        "strategy_name": "fake_direct_strategy",
        "llm_profile": "fake_local_profile",
    }

    invocation = service.invocations[0]
    request_context = cast(object, invocation.request_context)
    assert getattr(request_context, "session_id") == "session_123"
    assert getattr(request_context, "trace_id") == "trace_test_12345678"
    assert getattr(request_context, "metadata")["client"] == "web"


@pytest.mark.asyncio
async def test_fake_session_service_reset_clears_saved_state() -> None:
    service = FakeSessionService()
    context = to_session_context()

    await service.handle_chat(
        request=build_session_chat_request(
            message="hello",
            session_id="session_123",
            usecase=None,
        ),
        context=context,
    )
    reset_result = await service.reset_session(
        session_id="session_123",
        reason="user_requested",
        context=context,
    )

    assert reset_result.reset is True
    assert reset_result.session_id == "session_123"
    assert "session_123" not in service.states
    assert service.invocations[-1].metadata == {"reason": "user_requested"}


@pytest.mark.asyncio
async def test_fake_session_service_streams_events_in_order() -> None:
    service = FakeSessionService()
    context = to_session_context()

    events = [
        event
        async for event in service.stream_chat(
            request=build_session_chat_request(
                message="stream this",
                session_id="session_456",
                usecase=None,
            ),
            context=context,
        )
    ]

    assert [event.event_type for event in events] == [
        "response.started",
        "response.delta",
        "response.delta",
        "response.metadata",
        "response.completed",
    ]
    assert all(event.session_id == "session_456" for event in events)
    assert events[-1].data["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_fake_session_service_lists_and_deletes_sessions() -> None:
    service = FakeSessionService()
    context = to_session_context()

    await service.handle_chat(
        request=build_session_chat_request(message="hello", session_id="session_123", usecase=None),
        context=context,
    )
    await service.handle_chat(
        request=build_session_chat_request(message="hi", session_id="session_456", usecase=None),
        context=context,
    )

    listed = await service.list_sessions(limit=1, context=context)
    deleted = await service.delete_session(session_id="session_123", context=context)

    assert listed.limit == 1
    assert listed.has_more is True
    assert [item.session_id for item in listed.sessions] == ["session_123"]
    assert deleted.deleted is True
    assert "session_123" not in service.states
