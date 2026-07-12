from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.request_context import ApiRequestContext
from app.api.schemas import (
    ApiErrorDetail,
    ApiErrorResponse,
    ChatRequest,
    ChatResponse,
    ResetSessionRequest,
    ResetSessionResponse,
)
from app.session.models import SessionChatResult, SessionResetResult


def build_request_context() -> ApiRequestContext:
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


def test_chat_request_normalizes_values_and_keeps_metadata() -> None:
    request = ChatRequest(
        message="  hello world  ",
        session_id="  session_123  ",
        usecase="  support_chat  ",
        metadata={"client": "web", "timezone": "UTC"},
    )

    assert request.message == "hello world"
    assert request.session_id == "session_123"
    assert request.usecase == "support_chat"
    assert request.metadata == {"client": "web", "timezone": "UTC"}


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "   "},
        {"message": "hello", "metadata": {"authorization": "Bearer secret"}},
        {"message": "hello", "metadata": {"password_hint": "secret"}},
        {"message": "hello", "metadata": {"nested": object()}},
    ],
)
def test_chat_request_rejects_invalid_payloads(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(payload)


def test_reset_session_request_normalizes_reason() -> None:
    request = ResetSessionRequest(reason="  user_requested  ")

    assert request.reason == "user_requested"


def test_chat_response_maps_from_session_result() -> None:
    result = SessionChatResult(
        answer="Echo: hello",
        session_id="session_123",
        trace_id="trace_test_12345678",
        agent_name="fake_session_agent",
        strategy_name="fake_direct_strategy",
        llm_profile="fake_local_profile",
        tool_calls=[{"tool_name": "search", "status": "completed"}],
        memory_updates=[{"scope": "project", "status": "skipped"}],
        artifacts=[
            {
                "artifact_id": "chart_123",
                "type": "chart",
                "chart_type": "bar",
                "title": "Revenue",
                "description": "Monthly revenue.",
                "renderer": "echarts",
                "spec_version": "1.0",
                "data_mode": "inline",
                "data": [{"month": "Jan", "revenue": 1200}],
                "data_ref": None,
                "encoding": {"x": "month", "y": ["revenue"]},
                "options": {},
                "warnings": [],
                "metadata": {"source": "workflow_state"},
            }
        ],
        metadata={
            "usecase": "support_chat",
            "message_count": 2,
            "artifact_count": 1,
            "artifact_delivery_mode": "inline",
            "context_summary_added": True,
            "context_summary_id": "chart_123",
            "context_summary_ids": ["chart_123"],
        },
    )

    response = ChatResponse.from_result(result)

    assert response.model_dump(mode="python") == {
        "schema_version": "1.0",
        "trace_id": "trace_test_12345678",
        "session_id": "session_123",
        "data": {
            "answer": "Echo: hello",
            "agent_name": "fake_session_agent",
            "strategy_name": "fake_direct_strategy",
            "llm_profile": "fake_local_profile",
            "tool_calls": [{"tool_name": "search", "status": "completed"}],
            "memory_updates": [{"scope": "project", "status": "skipped"}],
            "artifacts": [
                {
                    "artifact_id": "chart_123",
                    "type": "chart",
                    "chart_type": "bar",
                    "title": "Revenue",
                    "description": "Monthly revenue.",
                    "renderer": "echarts",
                    "spec_version": "1.0",
                    "data_mode": "inline",
                    "data": [{"month": "Jan", "revenue": 1200}],
                    "data_ref": None,
                    "encoding": {"x": "month", "y": ["revenue"]},
                    "options": {},
                    "warnings": [],
                    "metadata": {"source": "workflow_state"},
                }
            ],
        },
        "metadata": {
            "usecase": "support_chat",
            "message_count": 2,
            "artifact_count": 1,
            "artifact_delivery_mode": "inline",
            "context_summary_added": True,
            "context_summary_id": "chart_123",
            "context_summary_ids": ["chart_123"],
        },
    }


def test_reset_response_maps_from_session_result() -> None:
    result = SessionResetResult(
        session_id="session_123",
        trace_id="trace_test_12345678",
        reset=True,
        message="Session workflow state was reset.",
        metadata={"reason": "user_requested"},
    )

    response = ResetSessionResponse.from_result(result)

    assert response.model_dump(mode="python") == {
        "schema_version": "1.0",
        "trace_id": "trace_test_12345678",
        "session_id": "session_123",
        "data": {
            "reset": True,
            "message": "Session workflow state was reset.",
        },
        "metadata": {"reason": "user_requested"},
    }


def test_api_error_response_shape_is_stable() -> None:
    error = ApiErrorResponse(
        trace_id="trace_test_12345678",
        error=ApiErrorDetail(
            code="validation_error",
            message="The request is invalid.",
            retryable=False,
            details={"field": "message", "reason": "required"},
        ),
    )

    assert error.model_dump(mode="python") == {
        "schema_version": "1.0",
        "trace_id": "trace_test_12345678",
        "error": {
            "code": "validation_error",
            "message": "The request is invalid.",
            "retryable": False,
            "details": {"field": "message", "reason": "required"},
        },
    }
