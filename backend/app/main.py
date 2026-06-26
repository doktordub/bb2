"""FastAPI application factory for the backend foundation app."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.openapi import register_api_openapi_routes
from app.api.routes_chat import router as chat_router
from app.api.routes_capabilities import router as capabilities_router
from app.api.routes_debug_traces import router as debug_trace_router
from app.api.routes_health import router as health_router
from app.api.routes_sessions import router as sessions_router
from app.config.bootstrap import build_container
from app.config.settings import Settings, load_settings
from app.foundation.container import FoundationContainer
from app.observability.context import TraceContext, reset_trace_context, set_trace_context
from app.observability.errors import build_log_error_details
from app.observability.events import STARTUP_COMPLETED, STARTUP_FAILED, STARTUP_STARTED
from app.observability.ids import new_trace_id
from app.observability.logging import configure_logging
from app.observability.middleware import TraceIdMiddleware
from app.observability.redaction import Redactor

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the backend ASGI app without starting external dependencies."""

    resolved_settings = settings or load_settings()
    configure_logging(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        startup_trace_id = new_trace_id()
        container = None
        startup_token = set_trace_context(
            TraceContext(
                trace_id=startup_trace_id,
                request_id=startup_trace_id,
                component="backend.startup",
            )
        )
        try:
            logger.info(
                "Backend startup started",
                extra={
                    "component": "backend.startup",
                    "event_type": STARTUP_STARTED,
                    "status": "starting",
                },
            )

            container = await build_container(resolved_settings)
            app.state.container = container
            _configure_api_surface(app, container)
            await container.trace_recorder.record(
                event_type="startup",
                event_name=STARTUP_COMPLETED,
                component="backend.startup",
                trace_id=startup_trace_id,
                status="completed",
                payload={
                    "operation": "startup",
                    "config_summary": container.config_summary,
                },
            )
            logger.info(
                "Backend startup completed",
                extra={
                    "component": "backend.startup",
                    "event_type": STARTUP_COMPLETED,
                    "status": "ok",
                    "details": container.config_summary,
                },
            )
        except Exception as exc:
            logger.critical(
                "Backend startup failed",
                extra={
                    "component": "backend.startup",
                    "event_type": STARTUP_FAILED,
                    "status": "error",
                    **build_log_error_details(
                        exc,
                        redactor=Redactor(redact_secrets=True, max_chars=None),
                        details={
                            "config_path": str(resolved_settings.resolved_app_config_path),
                        },
                        include_stack_trace=False,
                    ),
                },
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            raise
        finally:
            reset_trace_context(startup_token)

        try:
            yield
        finally:
            if container is not None:
                await container.persistence.close()
            app.state.container = None

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.container = None
    app.state.api_surface_registered = False

    app.add_middleware(TraceIdMiddleware)
    register_exception_handlers(app)

    return app


app = create_app()


def _configure_api_surface(app: FastAPI, container: FoundationContainer) -> None:
    if getattr(app.state, "api_surface_registered", False):
        return

    api_settings = container.api_settings
    if api_settings is None or not api_settings.enabled:
        app.state.api_surface_registered = True
        return

    prefix = api_settings.base_path
    app.include_router(health_router, prefix=prefix)
    app.include_router(capabilities_router, prefix=prefix)
    app.include_router(chat_router, prefix=prefix)
    app.include_router(sessions_router, prefix=prefix)
    if api_settings.debug_routes.enabled:
        app.include_router(debug_trace_router, prefix=prefix)
    register_api_openapi_routes(app, api_settings=api_settings)
    app.openapi_schema = None
    app.state.api_surface_registered = True