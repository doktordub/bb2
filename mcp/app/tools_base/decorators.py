"""Helper decorators for normalizing MCP tool handler results."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import wraps
import inspect
from time import perf_counter
from typing import Any, ParamSpec, TypeVar

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel

from app.context import ToolRuntimeContext
from app.errors import MCPRateLimitError, ToolInputValidationError
from app.observability.context import (
    build_trace_context,
    build_trace_context_from_headers,
    reset_trace_context,
    set_trace_context,
)
from app.observability.events import (
    MCP_TOOL_CALL_CANCELLED,
    MCP_TOOL_CALL_COMPLETED,
    MCP_TOOL_CALL_FAILED,
    MCP_TOOL_CALL_STARTED,
    MCP_TOOL_CALL_TIMEOUT,
)
from app.observability.logging import emit_observability_event
from app.security.auth import AuthError
from app.security.arguments import assert_no_secret_like_arguments
from app.tools_base.results import ToolErrorEnvelope, ToolResultEnvelope


P = ParamSpec("P")
R = TypeVar("R")


def _normalize_result(value: Any) -> Any:
    if isinstance(value, (ToolResultEnvelope, ToolErrorEnvelope, BaseModel)):
        return value.model_dump(mode="python")
    return value


def structured_tool_result(function: Callable[P, R]) -> Callable[P, Any]:
    """Serialize Pydantic result envelopes into plain Python structures."""

    if inspect.iscoroutinefunction(function):

        @wraps(function)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            return _normalize_result(await function(*args, **kwargs))

        return async_wrapper

    @wraps(function)
    def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
        return _normalize_result(function(*args, **kwargs))

    return sync_wrapper


def observe_tool_call(
    context: ToolRuntimeContext,
    tool_name: str,
    *,
    capability_name: str | None = None,
    timeout_seconds: int | None = None,
) -> Callable[[Callable[P, R]], Callable[P, Any]]:
    """Record safe trace events and metrics around a tool invocation."""

    resolved_capability_name = capability_name or tool_name

    def decorator(function: Callable[P, R]) -> Callable[P, Any]:
        bound_logger = context.logger.bind(
            tool_name=tool_name,
            capability_name=resolved_capability_name,
        )

        if inspect.iscoroutinefunction(function):

            @wraps(function)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                trace_context = _build_call_trace_context(
                    context,
                    tool_name=tool_name,
                    capability_name=resolved_capability_name,
                )
                token = set_trace_context(trace_context)
                start_time = perf_counter()
                try:
                    _record_started_event(
                        context=context,
                        logger=bound_logger,
                        tool_name=tool_name,
                        capability_name=resolved_capability_name,
                    )
                    if timeout_seconds is not None:
                        async with asyncio.timeout(timeout_seconds):
                            result = await function(*args, **kwargs)
                    else:
                        result = await function(*args, **kwargs)
                    duration_ms = _duration_ms(start_time)
                    _record_result(
                        context=context,
                        logger=bound_logger,
                        tool_name=tool_name,
                        capability_name=resolved_capability_name,
                        duration_ms=duration_ms,
                        result=result,
                    )
                    return result
                except asyncio.TimeoutError as error:
                    _record_failure(
                        context=context,
                        logger=bound_logger,
                        event_name=MCP_TOOL_CALL_TIMEOUT,
                        tool_name=tool_name,
                        capability_name=resolved_capability_name,
                        duration_ms=_duration_ms(start_time),
                        status="timeout",
                        error_code="timeout",
                    )
                    raise ToolError("Tool request timed out.") from error
                except asyncio.CancelledError:
                    _record_failure(
                        context=context,
                        logger=bound_logger,
                        event_name=MCP_TOOL_CALL_CANCELLED,
                        tool_name=tool_name,
                        capability_name=resolved_capability_name,
                        duration_ms=_duration_ms(start_time),
                        status="cancelled",
                        error_code="cancelled",
                    )
                    raise
                except Exception as error:
                    root_error = _root_error(error)
                    _record_failure(
                        context=context,
                        logger=bound_logger,
                        event_name=MCP_TOOL_CALL_FAILED,
                        tool_name=tool_name,
                        capability_name=resolved_capability_name,
                        duration_ms=_duration_ms(start_time),
                        status="error",
                        error_code=_error_code(root_error),
                    )
                    raise _safe_tool_error(error) from error
                finally:
                    reset_trace_context(token)

            return async_wrapper

        @wraps(function)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            trace_context = _build_call_trace_context(
                context,
                tool_name=tool_name,
                capability_name=resolved_capability_name,
            )
            token = set_trace_context(trace_context)
            start_time = perf_counter()
            try:
                _record_started_event(
                    context=context,
                    logger=bound_logger,
                    tool_name=tool_name,
                    capability_name=resolved_capability_name,
                )
                result = function(*args, **kwargs)
                duration_ms = _duration_ms(start_time)
                _record_result(
                    context=context,
                    logger=bound_logger,
                    tool_name=tool_name,
                    capability_name=resolved_capability_name,
                    duration_ms=duration_ms,
                    result=result,
                )
                return result
            except Exception as error:
                root_error = _root_error(error)
                _record_failure(
                    context=context,
                    logger=bound_logger,
                    event_name=MCP_TOOL_CALL_FAILED,
                    tool_name=tool_name,
                    capability_name=resolved_capability_name,
                    duration_ms=_duration_ms(start_time),
                    status="error",
                    error_code=_error_code(root_error),
                )
                raise _safe_tool_error(error) from error
            finally:
                reset_trace_context(token)

        return sync_wrapper

    return decorator


def _validated_arguments(function: Callable[..., Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
    bound = inspect.signature(function).bind_partial(*args, **kwargs)
    return {
        name: value
        for name, value in bound.arguments.items()
        if name not in {"self", "cls"}
    }


def _guard_tool_invocation(
    function: Callable[..., Any],
    *,
    context: ToolRuntimeContext,
    tool_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> None:
    arguments = _validated_arguments(function, *args, **kwargs)
    if context.app_config.policy.reject_secret_like_arguments:
        try:
            assert_no_secret_like_arguments(arguments, tool_name=tool_name)
        except ToolInputValidationError as error:
            raise ToolError(str(error)) from error

    if context.auth is not None:
        try:
            context.auth.current_request_context(
                require_authenticated=context.app_config.security.inbound_auth.enabled
            )
        except AuthError as error:
            raise ToolError(error.public_message) from error


def guard_tool_call(
    context: ToolRuntimeContext,
    tool_name: str,
) -> Callable[[Callable[P, R]], Callable[P, Any]]:
    """Apply shared auth and secret-argument checks to a tool handler."""

    def decorator(function: Callable[P, R]) -> Callable[P, Any]:
        if inspect.iscoroutinefunction(function):

            @wraps(function)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                _guard_tool_invocation(
                    function,
                    context=context,
                    tool_name=tool_name,
                    args=args,
                    kwargs=dict(kwargs),
                )
                return await function(*args, **kwargs)

            return async_wrapper

        @wraps(function)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            _guard_tool_invocation(
                function,
                context=context,
                tool_name=tool_name,
                args=args,
                kwargs=dict(kwargs),
            )
            return function(*args, **kwargs)

        return sync_wrapper

    return decorator


def _build_call_trace_context(
    context: ToolRuntimeContext,
    *,
    tool_name: str,
    capability_name: str,
):
    request_context = None
    if context.auth is not None:
        try:
            request_context = context.auth.current_request_context(require_authenticated=False)
        except Exception:
            request_context = None

    if request_context is not None:
        return build_trace_context(
            trace_id=request_context.trace_id,
            request_id=request_context.request_id,
            caller_service=request_context.caller_service,
            server_name=context.server_name,
            tool_name=tool_name,
            capability_name=capability_name,
        )

    try:
        headers = get_http_headers()
    except Exception:
        headers = {}

    return build_trace_context_from_headers(
        headers,
        server_name=context.server_name,
        tool_name=tool_name,
        capability_name=capability_name,
    )


def _record_started_event(
    *,
    context: ToolRuntimeContext,
    logger: Any,
    tool_name: str,
    capability_name: str,
) -> None:
    emit_observability_event(
        logger,
        context.tracer,
        MCP_TOOL_CALL_STARTED,
        payload={
            "server_name": context.server_name,
            "tool_name": tool_name,
            "capability_name": capability_name,
            "status": "started",
        },
    )


def _record_result(
    *,
    context: ToolRuntimeContext,
    logger: Any,
    tool_name: str,
    capability_name: str,
    duration_ms: float,
    result: Any,
) -> None:
    is_error = _result_is_error(result)
    error_code = _result_error_code(result)
    status = "error" if is_error else "ok"
    payload = {
        "server_name": context.server_name,
        "tool_name": tool_name,
        "capability_name": capability_name,
        "status": status,
        "duration_ms": duration_ms,
        "result_count": _result_count(result),
        "truncated": _result_truncated(result),
    }
    if error_code is not None:
        payload["error_code"] = error_code

    emit_observability_event(
        logger,
        context.tracer,
        MCP_TOOL_CALL_FAILED if is_error else MCP_TOOL_CALL_COMPLETED,
        payload=payload,
        level="warning" if is_error else "info",
    )
    _record_metrics(
        context=context,
        tool_name=tool_name,
        capability_name=capability_name,
        status=status,
        duration_ms=duration_ms,
        error_code=error_code,
    )


def _record_failure(
    *,
    context: ToolRuntimeContext,
    logger: Any,
    event_name: str,
    tool_name: str,
    capability_name: str,
    duration_ms: float,
    status: str,
    error_code: str,
) -> None:
    emit_observability_event(
        logger,
        context.tracer,
        event_name,
        payload={
            "server_name": context.server_name,
            "tool_name": tool_name,
            "capability_name": capability_name,
            "status": status,
            "duration_ms": duration_ms,
            "error_code": error_code,
        },
        level="warning",
    )
    _record_metrics(
        context=context,
        tool_name=tool_name,
        capability_name=capability_name,
        status=status,
        duration_ms=duration_ms,
        error_code=error_code,
    )


def _record_metrics(
    *,
    context: ToolRuntimeContext,
    tool_name: str,
    capability_name: str,
    status: str,
    duration_ms: float,
    error_code: str | None,
) -> None:
    tags = {
        "tool_name": tool_name,
        "capability_name": capability_name,
        "status": status,
    }
    if error_code is not None:
        tags["error_code"] = error_code

    context.metrics.increment("mcp.tool.call.count", tags)
    context.metrics.timing("mcp.tool.duration_ms", duration_ms, tags)

    if status in {"error", "timeout", "cancelled"}:
        context.metrics.increment("mcp.tool.error.count", tags)
    if status == "timeout":
        context.metrics.increment("mcp.tool.timeout.count", tags)
    if error_code == "rate_limited":
        context.metrics.increment("mcp.tool.rate_limited.count", tags)


def _duration_ms(start_time: float) -> float:
    return round((perf_counter() - start_time) * 1000, 3)


def _root_error(error: Exception) -> Exception:
    if isinstance(error, ToolError) and isinstance(error.__cause__, Exception):
        return error.__cause__
    return error


def _error_code(error: Exception) -> str:
    if isinstance(error, ToolInputValidationError):
        return "validation_error"
    if isinstance(error, AuthError):
        return "auth_error"
    if isinstance(error, MCPRateLimitError):
        return "rate_limited"
    if isinstance(error, asyncio.TimeoutError):
        return "timeout"
    if isinstance(error, ToolError):
        return "tool_error"
    return "internal_error"


def _safe_tool_error(error: Exception) -> ToolError:
    if isinstance(error, ToolError):
        return error
    if isinstance(error, ToolInputValidationError):
        return ToolError(str(error))
    if isinstance(error, AuthError):
        return ToolError(error.public_message)
    if isinstance(error, MCPRateLimitError):
        return ToolError("Tool rate limit exceeded.")
    if isinstance(error, asyncio.TimeoutError):
        return ToolError("Tool request timed out.")
    return ToolError("Tool execution failed.")


def _result_count(value: Any) -> int | None:
    normalized = _normalize_result(value)
    if not isinstance(normalized, dict):
        return None
    if isinstance(normalized.get("result_count"), int):
        return normalized["result_count"]
    summary = normalized.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("item_count"), int):
        return summary["item_count"]
    results = normalized.get("results")
    if isinstance(results, list):
        return len(results)
    return None


def _result_truncated(value: Any) -> bool:
    normalized = _normalize_result(value)
    if not isinstance(normalized, dict):
        return False
    if isinstance(normalized.get("truncated"), bool):
        return normalized["truncated"]
    summary = normalized.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("truncated"), bool):
        return summary["truncated"]
    return False


def _result_error_code(value: Any) -> str | None:
    normalized = _normalize_result(value)
    if not isinstance(normalized, dict):
        return None
    error = normalized.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        return error["code"]
    errors = normalized.get("errors")
    if isinstance(errors, list) and errors:
        first_error = errors[0]
        if isinstance(first_error, dict) and isinstance(first_error.get("code"), str):
            return first_error["code"]
    code = normalized.get("code")
    if isinstance(code, str) and code.strip():
        return code
    return None


def _result_is_error(value: Any) -> bool:
    normalized = _normalize_result(value)
    return isinstance(normalized, dict) and normalized.get("ok") is False