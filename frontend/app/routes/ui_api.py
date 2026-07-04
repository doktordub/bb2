from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, jsonify, request, stream_with_context

from app.services import BackendJsonResult, BackendStreamResult, get_backend_client


ui_api_bp = Blueprint("ui_api", __name__, url_prefix="/ui-api")


@ui_api_bp.get("/backend/health")
def backend_health() -> Response:
    return _make_json_response(
        get_backend_client().request_json(
            "GET",
            "/health",
            query=_request_query_items(),
        )
    )


@ui_api_bp.get("/backend/capabilities")
def backend_capabilities() -> Response:
    return _make_json_response(
        get_backend_client().request_json(
            "GET",
            "/capabilities",
            query=_request_query_items(),
        )
    )


@ui_api_bp.post("/chat")
def post_chat() -> Response:
    return _make_json_response(
        get_backend_client().request_json(
            "POST",
            "/chat",
            json_body=_request_json_body(),
        )
    )


@ui_api_bp.post("/chat/stream")
def post_chat_stream() -> Response:
    result = get_backend_client().stream_request(
        "POST",
        "/chat/stream",
        json_body=_request_json_body(),
    )
    if isinstance(result, BackendJsonResult):
        return _make_json_response(result)

    response = Response(stream_with_context(result.chunks), status=result.status_code)
    for name, value in result.headers.items():
        response.headers[name] = value
    return response


@ui_api_bp.get("/sessions")
def list_sessions() -> Response:
    return _make_json_response(
        get_backend_client().request_json(
            "GET",
            "/sessions",
            query=_request_query_items(),
        )
    )


@ui_api_bp.get("/sessions/<session_id>/history")
def get_session_history(session_id: str) -> Response:
    return _make_json_response(
        get_backend_client().request_json(
            "GET",
            f"/sessions/{session_id}/history",
            query=_request_query_items(),
        )
    )


@ui_api_bp.post("/sessions/<session_id>/reset")
def reset_session(session_id: str) -> Response:
    return _make_json_response(
        get_backend_client().request_json(
            "POST",
            f"/sessions/{session_id}/reset",
            json_body=_request_json_body(),
        )
    )


@ui_api_bp.delete("/sessions/<session_id>")
def delete_session(session_id: str) -> Response:
    return _make_json_response(
        get_backend_client().request_json(
            "DELETE",
            f"/sessions/{session_id}",
            query=_request_query_items(),
        )
    )


def _request_query_items() -> list[tuple[str, str]]:
    return list(request.args.items(multi=True))


def _request_json_body() -> dict[str, Any] | None:
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return None


def _make_json_response(result: BackendJsonResult) -> Response:
    response = jsonify(result.payload)
    response.status_code = result.status_code
    for name, value in result.headers.items():
        response.headers[name] = value
    return response