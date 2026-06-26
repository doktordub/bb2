from __future__ import annotations

from typing import cast

import pytest

from app.api.request_context import ApiRequestContext
from app.api.schemas import ChatRequest
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


@pytest.mark.asyncio
async def test_fake_session_service_generates_stable_session_ids() -> None:
    service = FakeSessionService()
    context = build_context()

    first = await service.handle_chat(
        request=ChatRequest(message="hello"),
        context=context,
    )
    second = await service.handle_chat(
        request=ChatRequest(message="hello again"),
        context=context,
    )

    assert first.session_id == "session_0001"
    assert second.session_id == "session_0002"
    assert first.answer == "Echo: hello"
    assert second.answer == "Echo: hello again"


@pytest.mark.asyncio
async def test_fake_session_service_reuses_client_session_id_and_records_context() -> None:
    service = FakeSessionService()
    context = build_context()

    result = await service.handle_chat(
        request=ChatRequest(
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
    context = build_context()

    await service.handle_chat(
        request=ChatRequest(message="hello", session_id="session_123"),
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
    context = build_context()

    events = [
        event
        async for event in service.stream_chat(
            request=ChatRequest(message="stream this", session_id="session_456"),
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
