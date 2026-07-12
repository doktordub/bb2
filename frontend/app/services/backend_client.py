from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4

import httpx
from flask import current_app

from app.settings import Settings


logger = logging.getLogger(__name__)

FRONTEND_REQUEST_ID_HEADER = "X-Frontend-Request-Id"


@dataclass(frozen=True, slots=True)
class BackendJsonResult:
    status_code: int
    payload: dict[str, Any]
    headers: dict[str, str]
    request_id: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


@dataclass(frozen=True, slots=True)
class BackendStreamResult:
    status_code: int
    headers: dict[str, str]
    chunks: Iterator[bytes]
    request_id: str


class BackendClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    def request_json(
        self,
        method: str,
        path: str,
        *,
        query: Sequence[tuple[str, str]] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> BackendJsonResult:
        request_id = _build_frontend_request_id()
        try:
            with self._build_client(timeout_seconds or self._settings.backend_timeout_seconds) as client:
                response = client.request(
                    method=method,
                    url=path,
                    params=list(query or []),
                    json=json_body,
                    headers=self._build_headers(request_id=request_id, extra_headers=headers),
                )
        except httpx.TimeoutException as exc:
            return self._map_transport_error(
                exc,
                request_id=request_id,
                method=method,
                path=path,
                status_code=504,
                code="backend_timeout",
                message="The backend did not respond in time.",
            )
        except httpx.ConnectError as exc:
            return self._map_transport_error(
                exc,
                request_id=request_id,
                method=method,
                path=path,
                status_code=503,
                code="backend_unavailable",
                message="The backend service is currently unavailable.",
            )
        except httpx.HTTPError as exc:
            return self._map_transport_error(
                exc,
                request_id=request_id,
                method=method,
                path=path,
                status_code=502,
                code="backend_request_failed",
                message="The backend request failed.",
            )

        return self._map_json_response(
            response,
            request_id=request_id,
            method=method,
            path=path,
        )

    def stream_request(
        self,
        method: str,
        path: str,
        *,
        query: Sequence[tuple[str, str]] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> BackendJsonResult | BackendStreamResult:
        request_id = _build_frontend_request_id()
        client = self._build_client(self._settings.backend_stream_timeout_seconds)
        stream_context = client.stream(
            method=method,
            url=path,
            params=list(query or []),
            json=json_body,
            headers=self._build_headers(
                request_id=request_id,
                accept_header="text/event-stream",
                extra_headers=headers,
            ),
        )

        try:
            response = stream_context.__enter__()
        except httpx.TimeoutException as exc:
            client.close()
            return self._map_transport_error(
                exc,
                request_id=request_id,
                method=method,
                path=path,
                status_code=504,
                code="backend_timeout",
                message="The backend did not respond in time.",
            )
        except httpx.ConnectError as exc:
            client.close()
            return self._map_transport_error(
                exc,
                request_id=request_id,
                method=method,
                path=path,
                status_code=503,
                code="backend_unavailable",
                message="The backend service is currently unavailable.",
            )
        except httpx.HTTPError as exc:
            client.close()
            return self._map_transport_error(
                exc,
                request_id=request_id,
                method=method,
                path=path,
                status_code=502,
                code="backend_request_failed",
                message="The backend request failed.",
            )

        if response.status_code >= 400:
            try:
                response.read()
                return self._map_json_response(
                    response,
                    request_id=request_id,
                    method=method,
                    path=path,
                )
            finally:
                stream_context.__exit__(None, None, None)
                client.close()

        headers = _filter_response_headers(response.headers)
        logger.info(
            "Frontend stream proxy connected",
            extra={
                "component": "frontend.backend_client",
                "event_type": "backend_stream_connected",
                "details": _safe_log_fields(
                    request_id=request_id,
                    method=method,
                    path=path,
                    status_code=response.status_code,
                ),
            },
        )

        def iter_chunks() -> Iterator[bytes]:
            try:
                for chunk in response.iter_bytes():
                    if chunk:
                        yield chunk
            except httpx.HTTPError:
                logger.warning(
                    "Frontend stream proxy interrupted",
                    extra={
                        "component": "frontend.backend_client",
                        "event_type": "backend_stream_interrupted",
                        "details": _safe_log_fields(
                            request_id=request_id,
                            method=method,
                            path=path,
                            status_code=response.status_code,
                        ),
                    },
                )
            finally:
                stream_context.__exit__(None, None, None)
                client.close()

        return BackendStreamResult(
            status_code=response.status_code,
            headers=headers,
            chunks=iter_chunks(),
            request_id=request_id,
        )

    def _build_client(self, timeout_seconds: int) -> httpx.Client:
        return httpx.Client(
            base_url=self._settings.backend_base_url,
            follow_redirects=False,
            timeout=httpx.Timeout(timeout_seconds),
            transport=self._transport,
        )

    def _build_headers(
        self,
        *,
        request_id: str,
        accept_header: str = "application/json",
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        return {
            "Accept": accept_header,
            FRONTEND_REQUEST_ID_HEADER: request_id,
            **{
                str(name): value
                for name, value in dict(extra_headers or {}).items()
                if isinstance(name, str) and isinstance(value, str) and value.strip()
            },
        }

    def _map_json_response(
        self,
        response: httpx.Response,
        *,
        request_id: str,
        method: str,
        path: str,
    ) -> BackendJsonResult:
        payload = _extract_json_payload(response)
        headers = _filter_response_headers(response.headers)

        if response.status_code >= 400:
            return BackendJsonResult(
                status_code=response.status_code,
                payload=_build_error_payload(
                    status_code=response.status_code,
                    request_id=request_id,
                    backend_payload=payload,
                    trace_id=_extract_trace_id(response=response, payload=payload),
                ),
                headers=headers,
                request_id=request_id,
            )

        if payload is None:
            logger.warning(
                "Frontend proxy received invalid JSON",
                extra={
                    "component": "frontend.backend_client",
                    "event_type": "backend_invalid_json",
                    "details": _safe_log_fields(
                        request_id=request_id,
                        method=method,
                        path=path,
                        status_code=response.status_code,
                    ),
                },
            )
            return BackendJsonResult(
                status_code=502,
                payload=_build_error_payload(
                    status_code=502,
                    request_id=request_id,
                    code="backend_invalid_response",
                    message="The backend returned an invalid JSON response.",
                    trace_id=_extract_trace_id(response=response, payload=None),
                ),
                headers=headers,
                request_id=request_id,
            )

        logger.info(
            "Frontend proxy request completed",
            extra={
                "component": "frontend.backend_client",
                "event_type": "backend_request_completed",
                "details": _safe_log_fields(
                    request_id=request_id,
                    method=method,
                    path=path,
                    status_code=response.status_code,
                ),
            },
        )
        return BackendJsonResult(
            status_code=response.status_code,
            payload=payload,
            headers=headers,
            request_id=request_id,
        )

    def _map_transport_error(
        self,
        exc: httpx.HTTPError,
        *,
        request_id: str,
        method: str,
        path: str,
        status_code: int,
        code: str,
        message: str,
    ) -> BackendJsonResult:
        logger.warning(
            "Frontend proxy request failed",
            extra={
                "component": "frontend.backend_client",
                "event_type": "backend_request_failed",
                "details": {
                    **_safe_log_fields(
                        request_id=request_id,
                        method=method,
                        path=path,
                        status_code=status_code,
                    ),
                    "error_type": type(exc).__name__,
                },
            },
        )
        return BackendJsonResult(
            status_code=status_code,
            payload=_build_error_payload(
                status_code=status_code,
                request_id=request_id,
                code=code,
                message=message,
            ),
            headers={"Content-Type": "application/json"},
            request_id=request_id,
        )


def build_backend_client(settings: Settings) -> BackendClient:
    return BackendClient(settings)


def get_backend_client() -> BackendClient:
    client = current_app.extensions.get("backend_client")
    if client is None:
        raise RuntimeError("Backend client was not registered on the Flask app.")
    return client


def _build_frontend_request_id() -> str:
    return f"frontend-{uuid4().hex}"


def _extract_json_payload(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _extract_trace_id(*, response: httpx.Response, payload: dict[str, Any] | None) -> str | None:
    if payload is not None:
        trace_id = payload.get("trace_id")
        if isinstance(trace_id, str) and trace_id.strip():
            return trace_id

    for header_name, header_value in response.headers.items():
        lowered = header_name.lower()
        if lowered.endswith("trace-id") or lowered == "trace-id":
            cleaned = header_value.strip()
            if cleaned:
                return cleaned
    return None


def _filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
    filtered: dict[str, str] = {}
    for name, value in headers.items():
        lowered = name.lower()
        if lowered in {"cache-control", "content-type"} or lowered.startswith("x-"):
            filtered[_canonicalize_header_name(name)] = value
    if "Content-Type" not in filtered:
        filtered["Content-Type"] = "application/json"
    return filtered


def _canonicalize_header_name(name: str) -> str:
    return "-".join(part.capitalize() for part in name.split("-"))


def _build_error_payload(
    *,
    status_code: int,
    request_id: str,
    backend_payload: dict[str, Any] | None = None,
    code: str = "backend_request_failed",
    message: str = "The backend request failed.",
    trace_id: str | None = None,
) -> dict[str, Any]:
    resolved_code = code
    resolved_message = message
    resolved_details: list[Any] | dict[str, Any] = []

    if backend_payload is not None:
        error_payload = backend_payload.get("error")
        if isinstance(error_payload, dict):
            candidate_code = error_payload.get("code")
            candidate_message = error_payload.get("message")
            if isinstance(candidate_code, str) and candidate_code.strip():
                resolved_code = candidate_code
            if isinstance(candidate_message, str) and candidate_message.strip():
                resolved_message = candidate_message
            resolved_details = _normalize_error_details(error_payload.get("details"))
        else:
            resolved_details = _normalize_error_details(backend_payload.get("details"))

    return {
        "ok": False,
        "status": status_code,
        "error": {
            "code": resolved_code,
            "message": resolved_message,
            "details": resolved_details,
        },
        "trace_id": trace_id,
        "request_id": request_id,
    }


def _normalize_error_details(raw_details: Any) -> list[Any] | dict[str, Any]:
    if raw_details is None:
        return []
    if isinstance(raw_details, list):
        return raw_details
    if isinstance(raw_details, dict):
        errors = raw_details.get("errors")
        if isinstance(errors, list):
            return errors
        return raw_details
    return []


def _safe_log_fields(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
) -> dict[str, Any]:
    return {
        "frontend_request_id": request_id,
        "method": method,
        "path": path,
        "status_code": status_code,
    }