from __future__ import annotations

from app.session.mapping import (
    build_core_request_context,
    build_session_chat_request,
    build_session_request_context,
)


def test_build_session_request_context_preserves_safe_request_metadata() -> None:
    context = build_session_request_context(
        trace_id="trace-123",
        request_id="request-123",
        user_id="local_user",
        user_id_hash="user_hash_123",
        client_host="127.0.0.1",
        user_agent="pytest",
        path="/chat",
        method="POST",
        metadata={"auth_mode": "local"},
        headers_safe={"x-trace-id": "trace-123"},
    )

    assert context.trace_id == "trace-123"
    assert context.metadata == {
        "auth_mode": "local",
        "headers_safe": {"x-trace-id": "trace-123"},
    }


def test_build_core_request_context_merges_session_and_request_metadata() -> None:
    request_context = build_core_request_context(
        request=build_session_chat_request(
            message="hello there",
            session_id="session_123",
            usecase="support_chat",
            metadata={"client": "web", "timezone": "UTC"},
        ),
        context=build_session_request_context(
            trace_id="trace-session-map-0001",
            request_id="request-session-map-0001",
            user_id="local_user",
            user_id_hash="user_hash_123",
            client_host="127.0.0.1",
            user_agent="pytest",
            path="/chat",
            method="POST",
            metadata={"auth_mode": "local", "trace_id": "trace-session-map-0001"},
            headers_safe={"x-trace-id": "trace-session-map-0001"},
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
        "headers_safe": {"x-trace-id": "trace-session-map-0001"},
        "client": "web",
        "timezone": "UTC",
        "request_id": "request-session-map-0001",
        "path": "/chat",
        "method": "POST",
        "user_id_hash": "user_hash_123",
        "client_host": "127.0.0.1",
        "user_agent": "pytest",
    }