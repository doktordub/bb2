"""Thin chat routes for the backend API boundary."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
import logging
from time import perf_counter

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    get_api_request_context,
    get_api_settings as get_api_settings_dependency,
    get_foundation_container,
    get_session_service,
)
from app.api.errors import ApiError
from app.api.request_context import ApiRequestContext
from app.api.sse import (
    encode_completed,
    encode_heartbeat,
    encode_session_stream_event,
    encode_stream_error,
)
from app.api.schemas import ChatRequest, ChatResponse
from app.config.view import ApiSettings
from app.contracts.state import normalize_workflow_state_session_id
from app.foundation.container import FoundationContainer
from app.session.models import SessionStreamEvent
from app.session.service import SessionService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def post_chat(
    payload: ChatRequest,
    request: Request,
    response: Response,
    context: ApiRequestContext = Depends(get_api_request_context),
    session_service: SessionService = Depends(get_session_service),
    api_settings: ApiSettings = Depends(get_api_settings_dependency),
    container: FoundationContainer = Depends(get_foundation_container),
) -> ChatResponse:
    """Handle a non-streaming chat request through the session-service boundary."""

    prepared_request = _prepare_chat_request(
        payload=payload,
        request=request,
        api_settings=api_settings,
    )
    _validate_route_limits(prepared_request, api_settings=api_settings)

    started_at = perf_counter()
    result = await session_service.handle_chat(request=prepared_request, context=context)
    duration_ms = max(int((perf_counter() - started_at) * 1000), 0)

    chat_response = ChatResponse.from_result(result)
    response.headers[api_settings.tracing.response_trace_header] = chat_response.trace_id
    response.headers[api_settings.sessions.session_id_header] = chat_response.session_id

    request_size_bytes = getattr(request.state, "request_size_bytes", None)
    logger.info(
        "Chat request completed",
        extra={
            "component": "api.chat",
            "event_type": "chat_completed",
            "status": "ok",
            "duration_ms": duration_ms,
            "details": {
                "route": request.url.path,
                "message_length": len(prepared_request.message),
                "request_size_bytes": request_size_bytes,
                "session_id_present": prepared_request.session_id is not None,
                "status_code": 200,
            },
        },
    )

    await container.trace_recorder.record(
        event_type="chat",
        component="api.chat",
        trace_id=chat_response.trace_id,
        session_id=chat_response.session_id,
        status="completed",
        duration_ms=float(duration_ms),
        payload={
            "route_template": "/chat",
            "message_length": len(prepared_request.message),
            "request_size_bytes": request_size_bytes,
            "status_code": 200,
        },
    )
    return chat_response


@router.post("/chat/stream")
async def post_chat_stream(
    payload: ChatRequest,
    request: Request,
    context: ApiRequestContext = Depends(get_api_request_context),
    session_service: SessionService = Depends(get_session_service),
    api_settings: ApiSettings = Depends(get_api_settings_dependency),
    container: FoundationContainer = Depends(get_foundation_container),
) -> StreamingResponse:
    """Handle a streaming chat request through the session-service boundary."""

    if not bool(container.config.get("features.streaming_enabled", False)):
        raise ApiError(
            code="streaming_disabled",
            message="Streaming chat is not enabled.",
            status_code=404,
        )

    prepared_request = _prepare_chat_request(
        payload=payload,
        request=request,
        api_settings=api_settings,
    )
    _validate_route_limits(prepared_request, api_settings=api_settings)

    request_size_bytes = getattr(request.state, "request_size_bytes", None)
    started_at = perf_counter()
    stream_iterator = session_service.stream_chat(request=prepared_request, context=context)
    header_session_id = prepared_request.session_id

    try:
        first_event = await anext(stream_iterator)
    except StopAsyncIteration:
        first_event = SessionStreamEvent(
            event_type="response.completed",
            trace_id=context.trace_id,
            session_id=header_session_id or "",
            data={"finish_reason": "stop", "duration_ms": 0},
        )
    except Exception as exc:
        return _build_stream_error_response(
            api_settings=api_settings,
            trace_id=context.trace_id,
            session_id=header_session_id,
            exc=exc,
        )

    resolved_session_id = first_event.session_id or header_session_id or ""
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        api_settings.tracing.response_trace_header: context.trace_id,
    }
    if resolved_session_id:
        headers[api_settings.sessions.session_id_header] = resolved_session_id

    async def stream_body() -> AsyncIterator[str]:
        terminal_event_sent = False
        status = "completed"

        try:
            encoded_first = encode_session_stream_event(first_event, settings=api_settings.sse)
            if encoded_first is not None:
                yield encoded_first

            if first_event.event_type == "response.error":
                terminal_event_sent = True
                status = "failed"
                return

            if first_event.event_type == "response.completed":
                terminal_event_sent = True
                return

            async for stream_event in _iter_stream_events_with_heartbeats(
                stream_iterator,
                request=request,
                trace_id=context.trace_id,
                api_settings=api_settings,
            ):
                if stream_event is None:
                    yield encode_heartbeat(trace_id=context.trace_id, settings=api_settings.sse)
                    continue

                encoded = encode_session_stream_event(stream_event, settings=api_settings.sse)
                if encoded is not None:
                    yield encoded

                if stream_event.event_type == "response.error":
                    terminal_event_sent = True
                    status = "failed"
                    return

                if stream_event.event_type == "response.completed":
                    terminal_event_sent = True
                    return

            if (
                not terminal_event_sent
                and resolved_session_id
                and not await request.is_disconnected()
            ):
                duration_ms = max(int((perf_counter() - started_at) * 1000), 0)
                yield encode_completed(
                    trace_id=context.trace_id,
                    session_id=resolved_session_id,
                    duration_ms=duration_ms,
                    settings=api_settings.sse,
                )
                terminal_event_sent = True
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception:
            status = "failed"
            yield encode_stream_error(
                trace_id=context.trace_id,
                session_id=resolved_session_id or None,
                code="backend_error",
                message="The request failed.",
                retryable=True,
            )
        finally:
            duration_ms = max(int((perf_counter() - started_at) * 1000), 0)
            logger.info(
                "Streaming chat request completed",
                extra={
                    "component": "api.chat",
                    "event_type": "chat_stream_completed",
                    "status": status,
                    "duration_ms": duration_ms,
                    "details": {
                        "route": request.url.path,
                        "message_length": len(prepared_request.message),
                        "request_size_bytes": request_size_bytes,
                        "session_id_present": prepared_request.session_id is not None,
                    },
                },
            )
            await container.trace_recorder.record(
                event_type="chat",
                component="api.chat",
                trace_id=context.trace_id,
                session_id=resolved_session_id or None,
                status=status,
                duration_ms=float(duration_ms),
                payload={
                    "route_template": "/chat/stream",
                    "message_length": len(prepared_request.message),
                    "request_size_bytes": request_size_bytes,
                    "streaming": True,
                    "terminal_event_sent": terminal_event_sent,
                },
            )

    return StreamingResponse(
        stream_body(),
        media_type="text/event-stream",
        headers=headers,
    )


def _prepare_chat_request(
    *,
    payload: ChatRequest,
    request: Request,
    api_settings: ApiSettings,
) -> ChatRequest:
    resolved_session_id = payload.session_id
    header_name = api_settings.sessions.session_id_header
    header_session_id = request.headers.get(header_name)

    if resolved_session_id is None and api_settings.sessions.accept_client_session_id and header_session_id:
        resolved_session_id = _normalize_session_id(
            header_session_id,
            location=["header", header_name],
        )

    if resolved_session_id is not None:
        resolved_session_id = _normalize_session_id(
            resolved_session_id,
            location=["body", "session_id"],
        )
    elif not api_settings.sessions.create_session_when_missing:
        raise _validation_error(
            location=["body", "session_id"],
            message="session_id is required",
        )

    return payload.model_copy(update={"session_id": resolved_session_id})


def _validate_route_limits(payload: ChatRequest, *, api_settings: ApiSettings) -> None:
    if len(payload.message) > api_settings.request_limits.max_message_chars:
        raise _validation_error(
            location=["body", "message"],
            message="message exceeds the configured limit",
        )

    metadata_json = json.dumps(payload.metadata, sort_keys=True, separators=(",", ":"))
    if len(metadata_json.encode("utf-8")) > api_settings.request_limits.max_metadata_bytes:
        raise _validation_error(
            location=["body", "metadata"],
            message="metadata exceeds the configured limit",
        )


def _normalize_session_id(raw_value: str, *, location: list[str]) -> str:
    try:
        return normalize_workflow_state_session_id(raw_value)
    except ValueError as exc:
        raise ApiError(
            code="invalid_session_id",
            message="The session ID is invalid.",
            status_code=400,
            details={
                "errors": [
                    {
                        "loc": location,
                        "msg": "Value error, invalid session_id",
                        "type": "value_error",
                    }
                ]
            },
        ) from exc


def _validation_error(*, location: list[str], message: str) -> ApiError:
    return ApiError(
        code="validation_error",
        message="The request is invalid.",
        status_code=422,
        details={
            "errors": [
                {
                    "loc": location,
                    "msg": f"Value error, {message}",
                    "type": "value_error",
                }
            ]
        },
    )


def _build_stream_error_response(
    *,
    api_settings: ApiSettings,
    trace_id: str,
    session_id: str | None,
    exc: Exception,
) -> StreamingResponse:
    retryable = not isinstance(exc, ApiError)
    code = exc.code if isinstance(exc, ApiError) else "backend_error"
    message = exc.message if isinstance(exc, ApiError) else "The request failed."
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        api_settings.tracing.response_trace_header: trace_id,
    }
    if session_id:
        headers[api_settings.sessions.session_id_header] = session_id

    async def body() -> AsyncIterator[str]:
        yield encode_stream_error(
            trace_id=trace_id,
            session_id=session_id,
            code=code,
            message=message,
            retryable=retryable,
        )

    return StreamingResponse(body(), media_type="text/event-stream", headers=headers)


async def _iter_stream_events_with_heartbeats(
    stream_iterator: object,
    *,
    request: Request,
    trace_id: str,
    api_settings: ApiSettings,
) -> AsyncIterator[SessionStreamEvent | None]:
    heartbeat_seconds = api_settings.sse.heartbeat_seconds
    pending = asyncio.create_task(anext(stream_iterator))

    try:
        while True:
            if await request.is_disconnected():
                pending.cancel()
                await _cancel_pending(pending)
                return

            done, _ = await asyncio.wait({pending}, timeout=heartbeat_seconds)
            if not done:
                yield None
                continue

            try:
                stream_event = pending.result()
            except StopAsyncIteration:
                return

            yield stream_event
            pending = asyncio.create_task(anext(stream_iterator))
    finally:
        if not pending.done():
            pending.cancel()
            await _cancel_pending(pending)


async def _cancel_pending(task: asyncio.Task[object]) -> None:
    try:
        await task
    except (StopAsyncIteration, asyncio.CancelledError):
        return