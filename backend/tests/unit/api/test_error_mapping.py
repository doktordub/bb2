from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.contracts.errors import (
    MCPAuthenticationError,
    MCPTransportError,
    MemoryAdapterError,
    MemoryDisabledError,
    MemoryInvalidScopeError,
    ToolArgumentValidationError,
    ToolDisabledError,
    ToolNotFoundError,
    ToolPolicyDeniedError,
    ToolResultTooLargeError,
    ToolTimeoutError,
)
from app.config.settings import load_settings
from app.llm.errors import (
    LLMPolicyDeniedError,
    LLMProfileResolutionError,
    LLMProviderTimeoutError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMUnsupportedCapabilityError,
)
from app.main import create_app
from app.session.errors import (
    SessionConflictError,
    SessionDeleteDisabledError,
    SessionHistoryDisabledError,
    SessionHistoryUnavailableError,
    SessionListDisabledError,
    SessionNotFoundError,
    UnknownUseCaseError,
)


SETTINGS_ENV_VARS = [
    "APP_ENV",
    "APP_DEBUG",
    "APP_USECASE",
    "APP_CONFIG_PATH",
    "APP_CONFIG_OVERRIDE_PATH",
    "APP_DATA_DIR",
    "APP_CONFIG_STRICT",
    "BACKEND_HOST",
    "BACKEND_PORT",
    "BACKEND_RELOAD",
    "LOG_LEVEL",
    "LOG_JSON",
    "MCP_MAIN_URL",
    "LLM_LOCAL_QWEN_BASE_URL",
    "LLM_LOCAL_QWEN_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "MEMORY_STORE_CONFIG",
    "SQLITE_WORKFLOW_STATE_URL",
    "SQLITE_TRACE_URL",
]


def build_app(monkeypatch: pytest.MonkeyPatch, tmp_path) -> object:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


class RaisingChatSessionService:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def handle_chat(self, **_: object) -> object:
        raise self._error

    async def reset_session(self, **_: object) -> object:
        raise self._error

    async def stream_chat(self, **_: object) -> object:
        raise self._error

    async def get_history(self, **_: object) -> object:
        raise self._error

    async def list_sessions(self, **_: object) -> object:
        raise self._error

    async def delete_session(self, **_: object) -> object:
        raise self._error


def test_chat_validation_error_returns_stable_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post("/chat", json={"message": "   "})

    assert response.status_code == 422
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": response.headers["x-trace-id"],
        "error": {
            "code": "validation_error",
            "message": "The request is invalid.",
            "retryable": False,
            "details": {
                "errors": [
                    {
                        "loc": ["body", "message"],
                        "msg": "Value error, message must not be empty",
                        "type": "value_error",
                    }
                ]
            },
        },
    }


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code", "expected_retryable"),
    [
        (SessionNotFoundError(), 404, "session_not_found", False),
        (SessionConflictError(), 409, "session_conflict", True),
        (UnknownUseCaseError(), 400, "unknown_usecase", False),
    ],
)
def test_known_session_errors_map_to_stable_api_responses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    error: Exception,
    expected_status: int,
    expected_code: str,
    expected_retryable: bool,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        app.state.container = replace(
            app.state.container,
            session_service=RaisingChatSessionService(error),
        )
        response = client.post(
            "/chat",
            json={"message": "hello", "session_id": "session_123"},
        )

    assert response.status_code == expected_status
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": response.headers["x-trace-id"],
        "error": {
            "code": expected_code,
            "message": response.json()["error"]["message"],
            "retryable": expected_retryable,
            "details": {},
        },
    }


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code", "expected_retryable"),
    [
        (SessionHistoryDisabledError(), 404, "session_history_disabled", False),
        (SessionHistoryUnavailableError(), 503, "session_history_unavailable", True),
    ],
)
def test_history_session_errors_map_to_stable_api_responses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    error: Exception,
    expected_status: int,
    expected_code: str,
    expected_retryable: bool,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        app.state.container = replace(
            app.state.container,
            session_service=RaisingChatSessionService(error),
        )
        response = client.get("/sessions/session_123/history")

    assert response.status_code == expected_status
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": response.headers["x-trace-id"],
        "error": {
            "code": expected_code,
            "message": response.json()["error"]["message"],
            "retryable": expected_retryable,
            "details": {},
        },
    }


@pytest.mark.parametrize(
    ("method", "path", "error", "expected_status", "expected_code", "expected_retryable"),
    [
        ("get", "/sessions", SessionListDisabledError(), 404, "session_list_disabled", False),
        ("delete", "/sessions/session_123", SessionNotFoundError(), 404, "session_not_found", False),
        ("delete", "/sessions/session_123", SessionDeleteDisabledError(), 404, "session_delete_disabled", False),
    ],
)
def test_session_admin_errors_map_to_stable_api_responses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    method: str,
    path: str,
    error: Exception,
    expected_status: int,
    expected_code: str,
    expected_retryable: bool,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        app.state.container = replace(
            app.state.container,
            session_service=RaisingChatSessionService(error),
        )
        response = getattr(client, method)(path)

    assert response.status_code == expected_status
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": response.headers["x-trace-id"],
        "error": {
            "code": expected_code,
            "message": response.json()["error"]["message"],
            "retryable": expected_retryable,
            "details": {},
        },
    }


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code", "expected_retryable"),
    [
        (LLMProfileResolutionError("missing profile"), 400, "unknown_llm_profile", False),
        (
            LLMUnsupportedCapabilityError("streaming not supported"),
            400,
            "unsupported_llm_capability",
            False,
        ),
        (LLMPolicyDeniedError("denied"), 403, "policy_denied", False),
        (LLMProviderUnavailableError("provider down"), 503, "llm_unavailable", True),
        (LLMRateLimitError("try again later"), 503, "llm_rate_limited", True),
        (LLMProviderTimeoutError("timed out"), 504, "llm_timeout", True),
    ],
)
def test_llm_runtime_errors_map_to_stable_api_responses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    error: Exception,
    expected_status: int,
    expected_code: str,
    expected_retryable: bool,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        app.state.container = replace(
            app.state.container,
            session_service=RaisingChatSessionService(error),
        )
        response = client.post(
            "/chat",
            json={"message": "hello", "session_id": "session_123"},
        )

    assert response.status_code == expected_status
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": response.headers["x-trace-id"],
        "error": {
            "code": expected_code,
            "message": response.json()["error"]["message"],
            "retryable": expected_retryable,
            "details": {},
        },
    }


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code", "expected_retryable"),
    [
        (MemoryDisabledError("memory disabled"), 503, "memory_disabled", False),
        (MemoryInvalidScopeError("invalid scope"), 400, "memory_invalid_scope", False),
        (MemoryAdapterError("adapter failure"), 503, "memory_unavailable", True),
    ],
)
def test_memory_runtime_errors_map_to_stable_api_responses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    error: Exception,
    expected_status: int,
    expected_code: str,
    expected_retryable: bool,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        app.state.container = replace(
            app.state.container,
            session_service=RaisingChatSessionService(error),
        )
        response = client.post(
            "/chat",
            json={"message": "hello", "session_id": "session_123"},
        )

    assert response.status_code == expected_status
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": response.headers["x-trace-id"],
        "error": {
            "code": expected_code,
            "message": response.json()["error"]["message"],
            "retryable": expected_retryable,
            "details": {},
        },
    }


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code", "expected_retryable"),
    [
        (ToolNotFoundError("missing tool"), 404, "tool_not_found", False),
        (
            ToolArgumentValidationError("bad tool arguments"),
            400,
            "invalid_tool_arguments",
            False,
        ),
        (ToolPolicyDeniedError("denied"), 403, "policy_denied", False),
        (ToolDisabledError("disabled"), 403, "tool_disabled", False),
        (ToolResultTooLargeError("too large"), 502, "tool_result_too_large", False),
        (ToolTimeoutError("timed out"), 504, "tool_timeout", True),
        (MCPAuthenticationError("auth failed"), 503, "tool_authentication_failed", True),
        (MCPTransportError("transport failed"), 503, "tool_unavailable", True),
    ],
)
def test_tool_runtime_errors_map_to_stable_api_responses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    error: Exception,
    expected_status: int,
    expected_code: str,
    expected_retryable: bool,
) -> None:
    app = build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        app.state.container = replace(
            app.state.container,
            session_service=RaisingChatSessionService(error),
        )
        response = client.post(
            "/chat",
            json={"message": "hello", "session_id": "session_123"},
        )

    assert response.status_code == expected_status
    assert response.json() == {
        "schema_version": "1.0",
        "trace_id": response.headers["x-trace-id"],
        "error": {
            "code": expected_code,
            "message": response.json()["error"]["message"],
            "retryable": expected_retryable,
            "details": {},
        },
    }