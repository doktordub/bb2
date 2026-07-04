from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request

from app.services import BackendJsonResult, get_backend_client
from app.settings import Settings


admin_api_bp = Blueprint("admin_api", __name__, url_prefix="/ui-api")


@admin_api_bp.get("/debug/traces")
def search_debug_traces() -> Response:
    settings = _get_settings()
    if not settings.frontend_admin_enabled or not settings.frontend_debug_traces_enabled:
        return _disabled_response(
            status_code=404,
            code="debug_traces_disabled",
            message="Debug trace routes are disabled.",
        )

    return _make_json_response(
        get_backend_client().request_json(
            "GET",
            "/debug/traces",
            query=_request_query_items(),
        )
    )


@admin_api_bp.get("/debug/traces/<trace_id>")
def get_debug_trace(trace_id: str) -> Response:
    settings = _get_settings()
    if not settings.frontend_admin_enabled or not settings.frontend_debug_traces_enabled:
        return _disabled_response(
            status_code=404,
            code="debug_traces_disabled",
            message="Debug trace routes are disabled.",
        )

    return _make_json_response(
        get_backend_client().request_json(
            "GET",
            f"/debug/traces/{trace_id}",
            query=_request_query_items(),
        )
    )


@admin_api_bp.post("/admin/restart")
def post_admin_restart() -> Response:
    settings = _get_settings()
    if not settings.frontend_admin_enabled or not settings.frontend_restart_enabled:
        return _disabled_response(
            status_code=404,
            code="restart_disabled",
            message="Restart control is disabled.",
        )

    return _make_json_response(
        get_backend_client().request_json(
            "POST",
            "/restart",
            json_body=_request_json_body(),
        )
    )


def _get_settings() -> Settings:
    settings = current_app.config["FRONTEND_SETTINGS"]
    if not isinstance(settings, Settings):
        raise RuntimeError("Flask frontend settings were not loaded correctly.")
    return settings


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


def _disabled_response(*, status_code: int, code: str, message: str) -> Response:
    response = jsonify(
        {
            "ok": False,
            "status": status_code,
            "error": {
                "code": code,
                "message": message,
                "details": [],
            },
            "trace_id": None,
        }
    )
    response.status_code = status_code
    return response