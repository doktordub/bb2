from pathlib import Path
from typing import Any

import pytest

from app import create_app
from app.services.backend_client import BackendJsonResult, BackendStreamResult
from app.settings import load_settings


SETTINGS_ENV_VARS = [
    "FRONTEND_ENV",
    "FRONTEND_HOST",
    "FRONTEND_PORT",
    "FRONTEND_DEBUG",
    "FRONTEND_TESTING",
    "FRONTEND_SECRET_KEY",
    "BACKEND_BASE_URL",
    "BACKEND_TIMEOUT_SECONDS",
    "BACKEND_STREAM_TIMEOUT_SECONDS",
    "FRONTEND_ADMIN_ENABLED",
    "FRONTEND_DEBUG_TRACES_ENABLED",
    "FRONTEND_RESTART_ENABLED",
    "FRONTEND_HELP_MARKDOWN_PATH",
    "FRONTEND_STATIC_VERSION",
]


class RecordingBackendClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: list[tuple[str, str]] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> BackendJsonResult:
        self.calls.append(
            {
                "kind": "json",
                "method": method,
                "path": path,
                "query": list(query or []),
                "json_body": json_body,
                "timeout_seconds": timeout_seconds,
                "headers": dict(headers or {}),
            }
        )
        return BackendJsonResult(
            status_code=200,
            payload={
                "method": method,
                "path": path,
                "query": list(query or []),
                "json_body": json_body,
            },
            headers={"X-Proxy-Test": "ok"},
            request_id="frontend-test",
        )

    def stream_request(
        self,
        method: str,
        path: str,
        *,
        query: list[tuple[str, str]] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> BackendStreamResult:
        self.calls.append(
            {
                "kind": "stream",
                "method": method,
                "path": path,
                "query": list(query or []),
                "json_body": json_body,
            }
        )
        return BackendStreamResult(
            status_code=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
            },
            chunks=iter([b"data: stream-ready\n\n"]),
            request_id="frontend-stream",
        )


def build_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    admin_enabled: bool = True,
    debug_enabled: bool = True,
    restart_enabled: bool = False,
) -> tuple[Any, RecordingBackendClient]:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    help_path = tmp_path / "Training_Readme.md"
    help_path.write_text("# Training\n\nProxy tests.", encoding="utf-8")

    monkeypatch.setenv("FRONTEND_TESTING", "true")
    monkeypatch.setenv("FRONTEND_ADMIN_ENABLED", "true" if admin_enabled else "false")
    monkeypatch.setenv(
        "FRONTEND_DEBUG_TRACES_ENABLED",
        "true" if debug_enabled else "false",
    )
    monkeypatch.setenv(
        "FRONTEND_RESTART_ENABLED",
        "true" if restart_enabled else "false",
    )
    monkeypatch.setenv("FRONTEND_HELP_MARKDOWN_PATH", help_path.as_posix())

    app = create_app(load_settings(load_env=False))
    backend_client = RecordingBackendClient()
    app.extensions["backend_client"] = backend_client
    return app.test_client(), backend_client


def test_health_proxy_route_maps_to_backend_health(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, backend_client = build_client(monkeypatch, tmp_path)

    response = client.get("/ui-api/backend/health")

    assert response.status_code == 200
    assert response.get_json()["path"] == "/health"
    assert backend_client.calls[0]["method"] == "GET"
    assert backend_client.calls[0]["path"] == "/health"


def test_chat_proxy_route_forwards_request_body(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, backend_client = build_client(monkeypatch, tmp_path)

    response = client.post(
        "/ui-api/chat",
        json={"message": "hello", "session_id": None, "usecase": "default_chat"},
    )

    assert response.status_code == 200
    assert response.get_json()["path"] == "/chat"
    assert backend_client.calls[0]["method"] == "POST"
    assert backend_client.calls[0]["json_body"] == {
        "message": "hello",
        "session_id": None,
        "usecase": "default_chat",
    }


def test_session_history_proxy_preserves_query_params(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, backend_client = build_client(monkeypatch, tmp_path)

    response = client.get("/ui-api/sessions/session-123/history?limit=25")

    assert response.status_code == 200
    assert response.get_json()["path"] == "/sessions/session-123/history"
    assert backend_client.calls[0]["query"] == [("limit", "25")]


def test_artifact_proxy_forwards_session_header_and_query_params(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, backend_client = build_client(monkeypatch, tmp_path)

    response = client.get(
        "/ui-api/artifacts/chart-123?return_type=artifact",
        headers={"X-Session-Id": "session-123"},
    )

    assert response.status_code == 200
    assert response.get_json()["path"] == "/artifacts/chart-123"
    assert backend_client.calls[0]["query"] == [("return_type", "artifact")]
    assert backend_client.calls[0]["headers"] == {"X-Session-Id": "session-123"}


def test_reset_proxy_forwards_json_body(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, backend_client = build_client(monkeypatch, tmp_path)

    response = client.post("/ui-api/sessions/session-123/reset", json={"reason": "user_request"})

    assert response.status_code == 200
    assert response.get_json()["json_body"] == {"reason": "user_request"}
    assert backend_client.calls[0]["path"] == "/sessions/session-123/reset"


def test_delete_proxy_uses_delete_method(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, backend_client = build_client(monkeypatch, tmp_path)

    response = client.delete("/ui-api/sessions/session-123")

    assert response.status_code == 200
    assert response.get_json()["path"] == "/sessions/session-123"
    assert backend_client.calls[0]["method"] == "DELETE"


def test_stream_proxy_passes_through_event_stream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, backend_client = build_client(monkeypatch, tmp_path)

    response = client.post("/ui-api/chat/stream", json={"message": "hello"})

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/event-stream"
    assert b"data: stream-ready" in response.data
    assert backend_client.calls[0]["kind"] == "stream"
    assert backend_client.calls[0]["path"] == "/chat/stream"


def test_debug_routes_are_disabled_by_frontend_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, backend_client = build_client(monkeypatch, tmp_path, debug_enabled=False)

    response = client.get("/ui-api/debug/traces")

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "debug_traces_disabled"
    assert response.get_json()["error"]["details"] == []
    assert backend_client.calls == []


def test_restart_route_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, backend_client = build_client(monkeypatch, tmp_path)

    response = client.post("/ui-api/admin/restart")

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "restart_disabled"
    assert response.get_json()["error"]["details"] == []
    assert backend_client.calls == []


def test_debug_trace_search_proxy_preserves_supported_filters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, backend_client = build_client(monkeypatch, tmp_path)

    response = client.get(
        "/ui-api/debug/traces?status=completed&errors_only=true&usecase=default_chat&event_name=request_received&event_type=request&limit=5"
    )

    assert response.status_code == 200
    assert response.get_json()["path"] == "/debug/traces"
    assert backend_client.calls[0]["query"] == [
        ("status", "completed"),
        ("errors_only", "true"),
        ("usecase", "default_chat"),
        ("event_name", "request_received"),
        ("event_type", "request"),
        ("limit", "5"),
    ]


def test_debug_trace_detail_proxy_preserves_limit_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, backend_client = build_client(monkeypatch, tmp_path)

    response = client.get("/ui-api/debug/traces/trace-123?limit=25")

    assert response.status_code == 200
    assert response.get_json()["path"] == "/debug/traces/trace-123"
    assert backend_client.calls[0]["query"] == [("limit", "25")]


def test_restart_route_forwards_post_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, backend_client = build_client(monkeypatch, tmp_path, restart_enabled=True)

    response = client.post("/ui-api/admin/restart", json={})

    assert response.status_code == 200
    assert response.get_json()["path"] == "/restart"
    assert backend_client.calls[0]["method"] == "POST"
    assert backend_client.calls[0]["json_body"] == {}