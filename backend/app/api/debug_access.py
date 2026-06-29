"""Shared guards for debug-only API routes."""

from __future__ import annotations

from fastapi import Request

from app.api.errors import ApiError
from app.config.view import ApiSettings

LOCALHOST_NAMES = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def require_debug_access(*, request: Request, api_settings: ApiSettings) -> None:
    if not api_settings.debug_routes.enabled:
        raise ApiError(
            code="not_found",
            message="Resource not found.",
            status_code=404,
        )

    if not api_settings.debug_routes.require_localhost:
        return

    client_host = request.client.host if request.client is not None else None
    if client_host in LOCALHOST_NAMES:
        return

    raise ApiError(
        code="debug_access_denied",
        message="Debug trace routes require localhost access.",
        status_code=403,
    )