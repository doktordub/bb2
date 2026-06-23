"""Request tracing middleware for the backend foundation app."""

from contextvars import ContextVar
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.observability.models import TRACE_ID_HEADER

_trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


def get_trace_id() -> str | None:
    """Return the current request trace ID when one is active."""

    return _trace_id_var.get()


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Attach a stable request trace ID to request state, logs, and responses."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        incoming_trace_id = request.headers.get(TRACE_ID_HEADER)
        trace_id = incoming_trace_id.strip() if incoming_trace_id else ""
        if not trace_id:
            trace_id = str(uuid4())

        request.state.trace_id = trace_id
        token = _trace_id_var.set(trace_id)
        try:
            response = await call_next(request)
        finally:
            _trace_id_var.reset(token)

        response.headers[TRACE_ID_HEADER] = trace_id
        return response