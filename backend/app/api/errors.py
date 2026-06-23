"""Foundation API error handlers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config.loader import ConfigLoadError
from app.observability.models import ApiErrorEnvelope, ApiErrorModel, ErrorCode, TRACE_ID_HEADER

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiError(Exception):
    """Explicit API error for future route and service use."""

    code: ErrorCode
    message: str
    status_code: int
    details: dict[str, Any] = field(default_factory=dict)


def register_exception_handlers(app: FastAPI) -> None:
    """Register foundation exception handlers on the FastAPI app."""

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _build_error_response(
            request=_,
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=exc.details,
        )

    @app.exception_handler(ConfigLoadError)
    async def handle_config_error(request: Request, exc: ConfigLoadError) -> JSONResponse:
        logger.warning("Config load failed: %s", exc)
        return _build_error_response(
            request=request,
            code="CONFIG_LOAD_ERROR",
            message="Configuration could not be loaded.",
            status_code=500,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _build_error_response(
            request=request,
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            status_code=422,
            details={"errors": _sanitize_validation_errors(exc)},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        if exc.status_code == 404:
            return _build_error_response(
                request=request,
                code="NOT_FOUND",
                message="Resource not found.",
                status_code=404,
            )

        return _build_error_response(
            request=request,
            code="INTERNAL_ERROR",
            message="An internal server error occurred.",
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled request error", exc_info=exc)
        return _build_error_response(
            request=request,
            code="INTERNAL_ERROR",
            message="An internal server error occurred.",
            status_code=500,
        )


def _build_error_response(
    *,
    request: Request,
    code: ErrorCode,
    message: str,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None)
    payload = ApiErrorEnvelope(
        error=ApiErrorModel(
            code=code,
            message=message,
            trace_id=trace_id,
            details=details or {},
        )
    )
    response = JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))
    if trace_id is not None:
        response.headers[TRACE_ID_HEADER] = trace_id
    return response


def _sanitize_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    sanitized_errors: list[dict[str, Any]] = []
    for error in exc.errors():
        sanitized_errors.append(
            {
                "loc": list(error.get("loc", [])),
                "msg": str(error.get("msg", "Invalid request.")),
                "type": str(error.get("type", "validation_error")),
            }
        )
    return sanitized_errors