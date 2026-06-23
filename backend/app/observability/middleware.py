"""Request tracing middleware for the backend foundation app."""

import logging
from time import perf_counter

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.observability.events import REQUEST_RECEIVED, RESPONSE_RETURNED
from app.observability.context import (
    TraceContext,
    get_trace_context as current_trace_context,
    get_trace_id as current_trace_id,
    reset_trace_context,
    set_trace_context,
)
from app.observability.ids import new_trace_id, resolve_incoming_trace_id
from app.observability.metrics import MetricsRecorder
from app.observability.models import TRACE_ID_HEADER
from app.observability.tracing import TraceRecorder

logger = logging.getLogger(__name__)


def get_trace_id() -> str | None:
    """Return the current request trace ID when one is active."""

    return current_trace_id()


def get_trace_context() -> TraceContext | None:
    """Return the current request trace context when one is active."""

    return current_trace_context()


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Attach a stable request trace ID to request state, logs, and responses."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        trace_id = resolve_incoming_trace_id(request.headers) or new_trace_id()
        route = _resolve_route(request)
        trace_context = TraceContext(
            trace_id=trace_id,
            request_id=trace_id,
            component="api.http",
        )

        request.state.trace_id = trace_id
        request.state.trace_context = trace_context
        token = set_trace_context(trace_context)
        trace_recorder = _get_trace_recorder(request)
        metrics = _get_metrics_recorder(request)
        started_at = perf_counter()

        try:
            await _record_request_received(
                trace_recorder=trace_recorder,
                trace_id=trace_id,
                method=request.method,
                route=route,
            )
            response = await call_next(request)
        finally:
            reset_trace_context(token)

        duration_ms = max(int((perf_counter() - started_at) * 1000), 0)
        status_code = response.status_code
        route = _resolve_route(request)

        _record_request_metrics(
            metrics=metrics,
            method=request.method,
            route=route,
            status_code=status_code,
            duration_ms=duration_ms,
        )
        await _record_request_completed(
            trace_recorder=trace_recorder,
            trace_id=trace_id,
            method=request.method,
            route=route,
            status_code=status_code,
            duration_ms=duration_ms,
        )
        logger.info(
            "Request completed",
            extra={
                "component": "api.http",
                "event_type": RESPONSE_RETURNED,
                "status": "ok" if status_code < 400 else "error",
                "duration_ms": duration_ms,
                "details": {
                    "method": request.method,
                    "route": route,
                    "status_code": status_code,
                },
            },
        )

        if trace_recorder is not None and duration_ms >= trace_recorder.settings.slow_request_ms:
            logger.warning(
                "Slow request detected",
                extra={
                    "component": "api.http",
                    "event_type": RESPONSE_RETURNED,
                    "status": "warning",
                    "duration_ms": duration_ms,
                    "details": {
                        "method": request.method,
                        "route": route,
                        "status_code": status_code,
                    },
                },
            )

        response.headers[TRACE_ID_HEADER] = trace_id
        return response


async def _record_request_received(
    *,
    trace_recorder: TraceRecorder | None,
    trace_id: str,
    method: str,
    route: str,
) -> None:
    logger.info(
        "Request started",
        extra={
            "component": "api.http",
            "event_type": REQUEST_RECEIVED,
            "status": "started",
            "details": {
                "method": method,
                "route": route,
                "streaming": False,
            },
        },
    )
    if trace_recorder is None:
        return

    await trace_recorder.record(
        event_type=REQUEST_RECEIVED,
        component="api.http",
        trace_id=trace_id,
        payload={
            "method": method,
            "route": route,
            "streaming": False,
        },
    )


async def _record_request_completed(
    *,
    trace_recorder: TraceRecorder | None,
    trace_id: str,
    method: str,
    route: str,
    status_code: int,
    duration_ms: int,
) -> None:
    if trace_recorder is None:
        return

    await trace_recorder.record(
        event_type=RESPONSE_RETURNED,
        component="api.http",
        trace_id=trace_id,
        payload={
            "method": method,
            "route": route,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "streaming": False,
        },
    )


def _record_request_metrics(
    *,
    metrics: MetricsRecorder | None,
    method: str,
    route: str,
    status_code: int,
    duration_ms: int,
) -> None:
    if metrics is None:
        return

    base_tags = {
        "method": method,
        "route": route,
    }
    metrics.increment("backend.requests.total", tags=base_tags)
    metrics.timing("backend.requests.duration_ms", duration_ms, tags=base_tags)

    if status_code >= 400:
        metrics.increment(
            "backend.requests.errors",
            tags={
                **base_tags,
                "status_code": str(status_code),
                "success": "false",
            },
        )


def _get_trace_recorder(request: Request) -> TraceRecorder | None:
    container = getattr(request.app.state, "container", None)
    trace_recorder = getattr(container, "trace_recorder", None)
    if isinstance(trace_recorder, TraceRecorder):
        return trace_recorder
    return None


def _get_metrics_recorder(request: Request) -> MetricsRecorder | None:
    container = getattr(request.app.state, "container", None)
    metrics = getattr(container, "metrics", None)
    if callable(getattr(metrics, "increment", None)) and callable(getattr(metrics, "timing", None)):
        return metrics
    return None


def _resolve_route(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path
    return request.url.path