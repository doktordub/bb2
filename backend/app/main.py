"""FastAPI application factory for the backend foundation app."""

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.routes_capabilities import router as capabilities_router
from app.api.routes_health import router as health_router
from app.config.bootstrap import build_container
from app.config.settings import Settings, load_settings
from app.observability.logging import configure_logging
from app.observability.middleware import TraceIdMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the backend ASGI app without starting external dependencies."""

    resolved_settings = settings or load_settings()
    configure_logging(resolved_settings)

    container = build_container(resolved_settings)

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        docs_url=resolved_settings.docs_url,
        redoc_url=resolved_settings.redoc_url,
    )
    app.state.container = container

    app.add_middleware(TraceIdMiddleware)
    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(capabilities_router)

    return app


app = create_app()