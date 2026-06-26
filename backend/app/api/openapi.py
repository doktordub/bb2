"""Helpers for config-driven OpenAPI and docs route registration."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse

from app.config.view import ApiSettings

_API_DOCS_REGISTERED_FLAG = "_api_docs_registered"


def register_api_openapi_routes(
    app: FastAPI,
    *,
    api_settings: ApiSettings,
) -> None:
    """Register config-driven OpenAPI and docs routes once per app instance."""

    if getattr(app.state, _API_DOCS_REGISTERED_FLAG, False):
        return

    if not api_settings.openapi_enabled:
        setattr(app.state, _API_DOCS_REGISTERED_FLAG, True)
        return

    base_path = api_settings.base_path
    openapi_path = _join_api_path(base_path, "/openapi.json")

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description="Thin REST and SSE backend boundary for chat, session, health, and capabilities routes.",
            routes=app.routes,
            tags=[
                {"name": "chat", "description": "Chat request/response routes."},
                {"name": "foundation", "description": "Backend health and capabilities routes."},
            ],
        )
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi

    @app.get(openapi_path, include_in_schema=False)
    async def openapi_schema() -> JSONResponse:
        return JSONResponse(app.openapi())

    if api_settings.docs_enabled:
        docs_path = _join_api_path(base_path, "/docs")
        redoc_path = _join_api_path(base_path, "/redoc")

        @app.get(docs_path, include_in_schema=False)
        async def swagger_docs() -> HTMLResponse:
            return get_swagger_ui_html(
                openapi_url=openapi_path,
                title=f"{app.title} - API Docs",
            )

        @app.get(redoc_path, include_in_schema=False)
        async def redoc_docs() -> HTMLResponse:
            return get_redoc_html(
                openapi_url=openapi_path,
                title=f"{app.title} - ReDoc",
            )

    setattr(app.state, _API_DOCS_REGISTERED_FLAG, True)


def _join_api_path(base_path: str, suffix: str) -> str:
    if not base_path:
        return suffix
    return f"{base_path.rstrip('/')}{suffix}"