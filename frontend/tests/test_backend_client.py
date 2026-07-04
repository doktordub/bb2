from pathlib import Path

import httpx

from app.services.backend_client import BackendClient, BackendJsonResult, BackendStreamResult
from app.settings import Settings


def build_settings(help_path: Path) -> Settings:
    return Settings(
        frontend_env="test",
        frontend_host="127.0.0.1",
        frontend_port=5000,
        frontend_debug=False,
        frontend_testing=True,
        frontend_secret_key="test-secret",
        backend_base_url="http://backend.test",
        backend_timeout_seconds=3,
        backend_stream_timeout_seconds=3,
        frontend_admin_enabled=True,
        frontend_debug_traces_enabled=True,
        frontend_restart_enabled=False,
        frontend_help_markdown_path=help_path,
        frontend_static_version="test",
    )


def test_request_json_preserves_backend_success_payload(tmp_path: Path) -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_headers
        seen_headers = dict(request.headers)
        assert request.method == "GET"
        assert str(request.url) == "http://backend.test/health"
        return httpx.Response(200, json={"status": "ok"}, headers={"x-trace-id": "trace-123"})

    client = BackendClient(
        build_settings(tmp_path / "help.md"),
        transport=httpx.MockTransport(handler),
    )

    result = client.request_json("GET", "/health")

    assert result.ok is True
    assert result.payload == {"status": "ok"}
    assert result.headers["X-Trace-Id"] == "trace-123"
    assert seen_headers["x-frontend-request-id"].startswith("frontend-")


def test_request_json_maps_backend_error_payload(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "trace_id": "trace-422",
                "error": {
                    "code": "backend_validation_error",
                    "message": "Backend validation failed.",
                    "details": {
                        "errors": [
                            {
                                "loc": ["body", "message"],
                                "msg": "Field required",
                                "type": "missing",
                            }
                        ]
                    },
                },
            },
        )

    client = BackendClient(
        build_settings(tmp_path / "help.md"),
        transport=httpx.MockTransport(handler),
    )

    result = client.request_json("POST", "/chat", json_body={})

    assert result.ok is False
    assert result.status_code == 422
    assert result.payload["error"]["code"] == "backend_validation_error"
    assert result.payload["error"]["details"][0]["loc"] == ["body", "message"]
    assert result.payload["trace_id"] == "trace-422"


def test_request_json_maps_connection_failures(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("backend offline", request=request)

    client = BackendClient(
        build_settings(tmp_path / "help.md"),
        transport=httpx.MockTransport(handler),
    )

    result = client.request_json("GET", "/health")

    assert result.ok is False
    assert result.status_code == 503
    assert result.payload["error"]["code"] == "backend_unavailable"


def test_request_json_maps_timeout_failures(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("backend timed out", request=request)

    client = BackendClient(
        build_settings(tmp_path / "help.md"),
        transport=httpx.MockTransport(handler),
    )

    result = client.request_json("GET", "/health")

    assert result.ok is False
    assert result.status_code == 504
    assert result.payload["error"]["code"] == "backend_timeout"


def test_request_json_maps_invalid_json_response(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", headers={"content-type": "application/json"})

    client = BackendClient(
        build_settings(tmp_path / "help.md"),
        transport=httpx.MockTransport(handler),
    )

    result = client.request_json("GET", "/health")

    assert result.ok is False
    assert result.status_code == 502
    assert result.payload["error"]["code"] == "backend_invalid_response"


def test_stream_request_yields_backend_chunks(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept"] == "text/event-stream"
        return httpx.Response(
            200,
            content=b"data: hello\n\ndata: world\n\n",
            headers={
                "content-type": "text/event-stream",
                "cache-control": "no-cache",
                "x-trace-id": "trace-stream",
            },
        )

    client = BackendClient(
        build_settings(tmp_path / "help.md"),
        transport=httpx.MockTransport(handler),
    )

    result = client.stream_request("POST", "/chat/stream", json_body={"message": "hello"})

    assert isinstance(result, BackendStreamResult)
    assert result.headers["Content-Type"] == "text/event-stream"
    assert b"data: hello" in b"".join(result.chunks)


def test_stream_request_maps_backend_error_json_payload(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "trace_id": "trace-stream-error",
                "error": {
                    "code": "stream_not_available",
                    "message": "Streaming is unavailable.",
                    "details": [],
                },
            },
            headers={"content-type": "application/json"},
        )

    client = BackendClient(
        build_settings(tmp_path / "help.md"),
        transport=httpx.MockTransport(handler),
    )

    result = client.stream_request("POST", "/chat/stream", json_body={"message": "hello"})

    assert isinstance(result, BackendJsonResult)
    assert result.status_code == 422
    assert result.payload["error"]["code"] == "stream_not_available"