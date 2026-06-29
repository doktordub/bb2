"""Backend-owned MCP transport wrapper over the installed MCP client library."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, Literal, Protocol, cast

import httpx
from mcp.client.session import ClientSession
from mcp.shared.session import ProgressFnT

from app.tools.errors import MCPAuthenticationError, MCPTransportError, ToolingConfigurationError
from app.tools.mcp.auth import MCPAuthProvider
from app.tools.mcp.errors import map_mcp_exception
from app.tools.mcp.event_stream import extract_error_message_from_call_result
from app.tools.mcp.protocol_models import MCPHealthResult

MCPTransportType = Literal["http", "sse", "websocket"]


class MCPTransport(Protocol):
    """Transport abstraction for MCP protocol requests and streaming."""

    async def request(
        self,
        *,
        method: str,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        ...

    def stream(
        self,
        *,
        method: str,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> AsyncIterator[dict[str, Any]]:
        ...

    async def health(self) -> MCPHealthResult:
        ...


class MCPTransportSession(Protocol):
    """Subset of ClientSession behavior used by the backend tool adapter."""

    async def list_tools(self, cursor: str | None = None, *, params: Any = None) -> Any:
        ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: timedelta | None = None,
        progress_callback: ProgressFnT | None = None,
        *,
        meta: dict[str, Any] | None = None,
    ) -> Any:
        ...

    async def send_ping(self) -> Any:
        ...


MCPTransportSessionFactory = Callable[..., Any]


class DefaultMCPTransport:
    """Concrete MCP transport that opens short-lived client sessions per request."""

    def __init__(
        self,
        *,
        endpoint: str | None,
        transport: MCPTransportType,
        auth_provider: MCPAuthProvider,
        auth_mode: str,
        default_timeout_seconds: int,
        default_stream_timeout_seconds: int,
        session_factory: MCPTransportSessionFactory | None = None,
        terminate_on_close: bool = True,
    ) -> None:
        self._endpoint = endpoint.strip() if isinstance(endpoint, str) and endpoint.strip() else None
        self._transport = transport
        self._auth_provider = auth_provider
        self._auth_mode = auth_mode
        self._default_timeout_seconds = max(1, default_timeout_seconds)
        self._default_stream_timeout_seconds = max(1, default_stream_timeout_seconds)
        self._session_factory = session_factory
        self._terminate_on_close = terminate_on_close

    async def request(
        self,
        *,
        method: str,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        self._ensure_configured()
        try:
            async with self._open_session(
                timeout_seconds=timeout_seconds,
                stream_timeout_seconds=max(timeout_seconds, self._default_stream_timeout_seconds),
            ) as session:
                if method == "tools/list":
                    result = await session.list_tools()
                elif method == "tools/call":
                    tool_name = _required_text(payload.get("name"), "MCP tool name is required.")
                    result = await session.call_tool(
                        tool_name,
                        _optional_mapping(payload.get("arguments")),
                        read_timeout_seconds=timedelta(seconds=max(1, timeout_seconds)),
                        meta=_optional_mapping(payload.get("meta")),
                    )
                elif method == "ping":
                    result = await session.send_ping()
                else:
                    raise ToolingConfigurationError(f"Unsupported MCP method: {method}")
        except BaseException as exc:
            mapped = map_mcp_exception(exc)
            if mapped is exc:
                raise
            raise mapped from exc

        return _model_dump(result)

    async def stream(
        self,
        *,
        method: str,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> AsyncIterator[dict[str, Any]]:
        self._ensure_configured()
        if method != "tools/call":
            raise ToolingConfigurationError("Streaming MCP transport only supports tools/call.")

        tool_name = _required_text(payload.get("name"), "MCP tool name is required.")
        stream_timeout_seconds = max(timeout_seconds, self._default_stream_timeout_seconds)
        progress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        call_task: asyncio.Task[Any] | None = None
        queue_task: asyncio.Task[dict[str, Any]] | None = None

        async def progress_callback(
            progress: float,
            total: float | None,
            message: str | None,
        ) -> None:
            event: dict[str, Any] = {
                "type": "progress",
                "progress": progress,
            }
            if total is not None:
                event["total"] = total
            if message is not None:
                event["message"] = message
            await progress_queue.put(event)

        try:
            async with self._open_session(
                timeout_seconds=timeout_seconds,
                stream_timeout_seconds=stream_timeout_seconds,
            ) as session:
                yield {"type": "started"}
                call_task = asyncio.create_task(
                    session.call_tool(
                        tool_name,
                        _optional_mapping(payload.get("arguments")),
                        read_timeout_seconds=timedelta(seconds=stream_timeout_seconds),
                        progress_callback=progress_callback,
                        meta=_optional_mapping(payload.get("meta")),
                    )
                )
                queue_task = asyncio.create_task(progress_queue.get())

                while True:
                    wait_set: set[asyncio.Task[Any]] = {call_task}
                    if queue_task is not None:
                        wait_set.add(queue_task)
                    done, _pending = await asyncio.wait(
                        wait_set,
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    if queue_task is not None and queue_task in done:
                        yield queue_task.result()
                        queue_task = asyncio.create_task(progress_queue.get())
                        continue

                    if call_task in done:
                        while not progress_queue.empty():
                            yield progress_queue.get_nowait()
                        result = await call_task
                        if result.isError:
                            yield {
                                "type": "error",
                                "error_message": extract_error_message_from_call_result(result),
                            }
                        else:
                            yield {
                                "type": "completed",
                                "result": _model_dump(result),
                            }
                        return
        except BaseException as exc:
            mapped = map_mcp_exception(exc)
            if mapped is exc:
                raise
            raise mapped from exc
        finally:
            if queue_task is not None and not queue_task.done():
                queue_task.cancel()
            if call_task is not None and not call_task.done():
                call_task.cancel()

    async def health(self) -> MCPHealthResult:
        if self._endpoint is None:
            return MCPHealthResult(
                status="not_configured",
                configured=False,
                endpoint=None,
                auth_mode=self._auth_mode,
                tool_count=0,
                metadata={
                    "transport": self._transport,
                    "provider": "mcp_client_session",
                },
            )

        try:
            async with self._open_session(
                timeout_seconds=self._default_timeout_seconds,
                stream_timeout_seconds=self._default_stream_timeout_seconds,
            ) as session:
                await session.send_ping()
        except BaseException as exc:
            mapped = map_mcp_exception(exc)
            if isinstance(mapped, asyncio.CancelledError):
                raise
            return MCPHealthResult(
                status="error",
                configured=True,
                endpoint=self._endpoint,
                auth_mode=self._auth_mode,
                tool_count=0,
                error=str(mapped),
                metadata={
                    "transport": self._transport,
                    "provider": "mcp_client_session",
                },
            )

        return MCPHealthResult(
            status="ok",
            configured=True,
            endpoint=self._endpoint,
            auth_mode=self._auth_mode,
            tool_count=0,
            metadata={
                "transport": self._transport,
                "provider": "mcp_client_session",
            },
        )

    @asynccontextmanager
    async def _open_session(
        self,
        *,
        timeout_seconds: int,
        stream_timeout_seconds: int,
    ) -> AsyncIterator[MCPTransportSession]:
        if self._session_factory is not None:
            async with self._session_factory(
                timeout_seconds=timeout_seconds,
                stream_timeout_seconds=stream_timeout_seconds,
            ) as session:
                yield cast(MCPTransportSession, session)
            return

        async with self._open_default_session(
            timeout_seconds=timeout_seconds,
            stream_timeout_seconds=stream_timeout_seconds,
        ) as session:
            yield cast(MCPTransportSession, session)

    @asynccontextmanager
    async def _open_default_session(
        self,
        *,
        timeout_seconds: int,
        stream_timeout_seconds: int,
    ) -> AsyncIterator[ClientSession]:
        endpoint = self._required_endpoint()
        headers = await self._auth_provider.get_headers()
        read_timeout = timedelta(seconds=max(1, stream_timeout_seconds))

        if self._transport == "http":
            from mcp.client.streamable_http import streamable_http_client

            async with httpx.AsyncClient(
                headers=headers or None,
                timeout=httpx.Timeout(timeout_seconds, read=stream_timeout_seconds),
                follow_redirects=False,
            ) as client:
                async with streamable_http_client(
                    endpoint,
                    http_client=client,
                    terminate_on_close=self._terminate_on_close,
                ) as (read_stream, write_stream, _get_session_id):
                    async with ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=read_timeout,
                    ) as session:
                        await session.initialize()
                        yield session
            return

        if self._transport == "sse":
            from mcp.client.sse import sse_client

            async with sse_client(
                endpoint,
                headers=headers or None,
                timeout=timeout_seconds,
                sse_read_timeout=stream_timeout_seconds,
            ) as (read_stream, write_stream):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=read_timeout,
                ) as session:
                    await session.initialize()
                    yield session
            return

        if headers:
            raise MCPAuthenticationError(
                "Configured MCP auth is not supported for WebSocket transport."
            )

        from mcp.client.websocket import websocket_client

        async with websocket_client(endpoint) as (read_stream, write_stream):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=read_timeout,
            ) as session:
                await session.initialize()
                yield session

    def _ensure_configured(self) -> None:
        if self._endpoint is None:
            raise MCPTransportError("The MCP endpoint is not configured.")
        if self._transport not in {"http", "sse", "websocket"}:
            raise ToolingConfigurationError("Unsupported MCP transport.")

    def _required_endpoint(self) -> str:
        self._ensure_configured()
        endpoint = self._endpoint
        if endpoint is None:
            raise MCPTransportError("The MCP endpoint is not configured.")
        return endpoint


def _model_dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(by_alias=True, mode="json", exclude_none=True)
        if isinstance(dumped, dict):
            return dumped
    if isinstance(value, dict):
        return dict(value)
    raise ValueError("MCP transport received a non-mapping response.")


def _optional_mapping(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    raise ValueError("Expected an object-shaped MCP payload field.")


def _required_text(value: object, message: str) -> str:
    if not isinstance(value, str):
        raise ValueError(message)
    normalized = value.strip()
    if not normalized:
        raise ValueError(message)
    return normalized


__all__ = [
    "DefaultMCPTransport",
    "MCPTransport",
    "MCPTransportSession",
    "MCPTransportSessionFactory",
    "MCPTransportType",
]