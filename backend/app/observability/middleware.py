"""Request tracing, request limits, and CORS middleware for the backend API."""

from collections.abc import Iterable
import logging
from time import perf_counter

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp, Message

from app.api.errors import build_api_error_response
from app.config.view import ApiSettings
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
        api_settings = _get_api_settings(request)
        prepared_request, request_size_bytes = await _prepare_request(request)
        request = prepared_request
        trace_id = _resolve_trace_id(request=request, api_settings=api_settings)
        route = _resolve_route(request)
        trace_header_name = _trace_response_header_name(api_settings)
        request.state.request_size_bytes = request_size_bytes
        _set_request_timeout_metadata(request=request, api_settings=api_settings)
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
        response: Response | None = None
        cors_origin = _resolve_cors_origin(request=request, api_settings=api_settings)

        try:
            await _record_request_received(
                trace_recorder=trace_recorder,
                trace_id=trace_id,
                method=request.method,
                route=route,
                enabled=_record_request_received_enabled(api_settings),
            )
            if _is_preflight_request(request=request, cors_origin=cors_origin, api_settings=api_settings):
                response = Response(status_code=200)
            elif _request_is_too_large(
                request_size_bytes=request_size_bytes,
                api_settings=api_settings,
            ):
                logger.warning(
                    "Request rejected because the body exceeded the configured limit",
                    extra={
                        "component": "api.http",
                        "event_type": RESPONSE_RETURNED,
                        "status": "error",
                        "details": {
                            "method": request.method,
                            "route": route,
                            "request_size_bytes": request_size_bytes,
                            "max_body_bytes": _max_body_bytes(api_settings),
                        },
                    },
                )
                response = build_api_error_response(
                    request=request,
                    code="request_too_large",
                    message="The request body exceeds the configured size limit.",
                    status_code=413,
                    details={
                        "limit_bytes": _max_body_bytes(api_settings),
                    },
                )
            else:
                response = await call_next(request)
        finally:
            reset_trace_context(token)

        duration_ms = max(int((perf_counter() - started_at) * 1000), 0)
        if response is None:
            raise RuntimeError("Request middleware did not produce a response.")
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
            enabled=_record_response_returned_enabled(api_settings),
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
                    "request_size_bytes": request_size_bytes,
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
                        "request_size_bytes": request_size_bytes,
                    },
                },
            )

        response.headers[trace_header_name] = trace_id
        _apply_cors_headers(
            response=response,
            request=request,
            api_settings=api_settings,
            cors_origin=cors_origin,
        )
        return response


async def _record_request_received(
    *,
    trace_recorder: TraceRecorder | None,
    trace_id: str,
    method: str,
    route: str,
    enabled: bool,
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
    if trace_recorder is None or not enabled:
        return

    await trace_recorder.record(
        event_type="request",
        event_name=REQUEST_RECEIVED,
        component="api.http",
        trace_id=trace_id,
        status="started",
        payload={
            "method": method,
            "route_template": route,
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
    enabled: bool,
) -> None:
    if trace_recorder is None or not enabled:
        return

    await trace_recorder.record(
        event_type="request",
        event_name=RESPONSE_RETURNED,
        component="api.http",
        trace_id=trace_id,
        status="failed" if status_code >= 500 else "completed",
        severity=(
            "error" if status_code >= 500 else "warning" if status_code >= 400 else "info"
        ),
        duration_ms=float(duration_ms),
        payload={
            "method": method,
            "route_template": route,
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


async def _prepare_request(request: Request) -> tuple[Request, int]:
    content_length = _parse_content_length(request.headers.get("content-length"))
    if content_length is not None:
        return request, content_length

    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return request, 0

    body = await request.body()

    async def receive() -> Message:
        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }

    return Request(request.scope, receive), len(body)


def _parse_content_length(raw_value: str | None) -> int | None:
    if raw_value is None:
        return None

    try:
        value = int(raw_value)
    except ValueError:
        return None

    return max(value, 0)


def _get_api_settings(request: Request) -> ApiSettings | None:
    container = getattr(request.app.state, "container", None)
    api_settings = getattr(container, "api_settings", None)
    if isinstance(api_settings, ApiSettings):
        return api_settings
    return None


def _resolve_trace_id(*, request: Request, api_settings: ApiSettings | None) -> str:
    if api_settings is not None and not api_settings.tracing.accept_client_trace_id:
        return new_trace_id()
    return resolve_incoming_trace_id(request.headers) or new_trace_id()


def _trace_response_header_name(api_settings: ApiSettings | None) -> str:
    if api_settings is None:
        return TRACE_ID_HEADER
    return api_settings.tracing.response_trace_header


def _set_request_timeout_metadata(*, request: Request, api_settings: ApiSettings | None) -> None:
    if api_settings is None:
        request.state.request_timeout_seconds = 120
        request.state.stream_timeout_seconds = 300
        return

    request.state.request_timeout_seconds = api_settings.request_limits.request_timeout_seconds
    request.state.stream_timeout_seconds = api_settings.request_limits.stream_timeout_seconds


def _record_request_received_enabled(api_settings: ApiSettings | None) -> bool:
    if api_settings is None:
        return True
    return api_settings.tracing.record_request_received


def _record_response_returned_enabled(api_settings: ApiSettings | None) -> bool:
    if api_settings is None:
        return True
    return api_settings.tracing.record_response_returned


def _max_body_bytes(api_settings: ApiSettings | None) -> int:
    if api_settings is None:
        return 1048576
    return api_settings.request_limits.max_body_bytes


def _request_is_too_large(*, request_size_bytes: int, api_settings: ApiSettings | None) -> bool:
    return request_size_bytes > _max_body_bytes(api_settings)


def _resolve_cors_origin(
    *,
    request: Request,
    api_settings: ApiSettings | None,
) -> str | None:
    if api_settings is None or not api_settings.cors.enabled:
        return None

    origin = request.headers.get("origin")
    if origin is None:
        return None

    allowed_origins = api_settings.cors.allow_origins
    if "*" in allowed_origins:
        if api_settings.cors.allow_credentials:
            return origin
        return "*"

    if origin in allowed_origins:
        return origin

    return None


def _is_preflight_request(
    *,
    request: Request,
    cors_origin: str | None,
    api_settings: ApiSettings | None,
) -> bool:
    if cors_origin is None:
        return False
    if api_settings is None or not api_settings.cors.enabled:
        return False
    return request.method == "OPTIONS" and request.headers.get("access-control-request-method") is not None


def _apply_cors_headers(
    *,
    response: Response,
    request: Request,
    api_settings: ApiSettings | None,
    cors_origin: str | None,
) -> None:
    if api_settings is None or not api_settings.cors.enabled or cors_origin is None:
        return

    response.headers["Access-Control-Allow-Origin"] = cors_origin
    response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Expose-Headers"] = ", ".join(
        _cors_exposed_headers(api_settings)
    )

    if api_settings.cors.allow_credentials:
        response.headers["Access-Control-Allow-Credentials"] = "true"

    if _is_preflight_request(request=request, cors_origin=cors_origin, api_settings=api_settings):
        response.headers["Access-Control-Allow-Methods"] = ", ".join(
            api_settings.cors.allow_methods
        )
        response.headers["Access-Control-Allow-Headers"] = ", ".join(
            _cors_allowed_headers(api_settings)
        )


def _cors_exposed_headers(api_settings: ApiSettings) -> tuple[str, ...]:
    return _unique_headers(
        (
            api_settings.tracing.response_trace_header,
            api_settings.sessions.session_id_header,
            "Content-Type",
        )
    )


def _cors_allowed_headers(api_settings: ApiSettings) -> tuple[str, ...]:
    return _unique_headers(
        (
            *api_settings.cors.allow_headers,
            api_settings.tracing.response_trace_header,
            api_settings.sessions.session_id_header,
        )
    )


def _unique_headers(headers: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for header_name in headers:
        normalized = header_name.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return tuple(unique)


def _resolve_route(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path
    return request.url.path