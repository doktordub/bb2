"""OpenAI-compatible HTTP adapter used by the concrete LLM gateway runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any, cast
from urllib.parse import urlsplit

import httpx

from app.config.view import LLMProviderSettings
from app.contracts.llm import LLMContentPart, LLMTokenUsage
from app.llm.errors import (
    LLMAuthenticationError,
    LLMBadRequestError,
    LLMMalformedResponseError,
    LLMProviderTimeoutError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
)
from app.llm.models import (
    ProviderCapabilities,
    ProviderHealthSummary,
    ProviderLLMResponse,
    ProviderLLMStreamEvent,
    ResolvedLLMRequest,
)

_CHAT_COMPLETIONS_PATH = "/chat/completions"
_FINISH_REASON_MAP = {
    "stop": "completed",
    "length": "length",
    "content_filter": "content_filter",
    "tool_calls": "tool_calls",
    "function_call": "tool_calls",
}


@dataclass(frozen=True, slots=True)
class _StreamingState:
    finish_reason: str | None = None
    usage: LLMTokenUsage | None = None


class OpenAICompatibleProviderAdapter:
    """HTTP-based adapter for OpenAI-compatible chat-completions endpoints."""

    def __init__(
        self,
        provider: LLMProviderSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._provider = provider
        self._client = client
        self.name = provider.name
        self.provider_type = provider.type
        self.capabilities = ProviderCapabilities(
            provider_name=provider.name,
            provider_type=provider.type,
            supports_streaming=True,
            supports_json_schema=True,
            supports_tool_calling=True,
        )

    async def complete(self, request: ResolvedLLMRequest) -> ProviderLLMResponse:
        try:
            response = await self._with_client(
                lambda client: client.post(
                    self._build_endpoint_url(),
                    headers=self._build_headers(),
                    json=self._build_request_body(request=request, stream=False),
                    timeout=request.timeout_seconds,
                )
            )
        except httpx.TimeoutException as exc:
            raise LLMProviderTimeoutError(
                "OpenAI-compatible provider timed out.",
                metadata={"provider": self.name},
            ) from exc
        except httpx.TransportError as exc:
            raise LLMProviderUnavailableError(
                "OpenAI-compatible provider is unavailable.",
                metadata={"provider": self.name},
            ) from exc

        self._raise_for_status(response.status_code)
        payload = self._parse_json(response)
        choice = _first_choice(payload)
        message = _mapping_value(choice, "message")
        text = _extract_text(message.get("content"))
        if text is None:
            raise LLMMalformedResponseError(
                "OpenAI-compatible provider returned no message content.",
                metadata={"provider": self.name},
            )

        return ProviderLLMResponse(
            text=text,
            finish_reason=_normalize_finish_reason(_string_value(choice, "finish_reason")),
            usage=_extract_usage(_mapping_value(payload, "usage")),
            raw_id=_string_value(payload, "id"),
            metadata=_safe_response_metadata(payload),
        )

    async def stream(self, request: ResolvedLLMRequest) -> AsyncIterator[ProviderLLMStreamEvent]:
        yield ProviderLLMStreamEvent.started()

        if self._client is not None:
            async for event in self._stream_with_client(self._client, request):
                yield event
            return

        async with httpx.AsyncClient() as client:
            async for event in self._stream_with_client(client, request):
                yield event

    async def health(self) -> ProviderHealthSummary:
        base_url_configured = bool(self._provider.base_url)
        available = self._provider.enabled and base_url_configured
        return ProviderHealthSummary(
            provider_name=self.name,
            provider_type=self.provider_type,
            status="ok" if available else "unavailable",
            enabled=self._provider.enabled,
            available=available,
            metadata={"base_url_configured": base_url_configured},
        )

    async def _stream_with_client(
        self,
        client: httpx.AsyncClient,
        request: ResolvedLLMRequest,
    ) -> AsyncIterator[ProviderLLMStreamEvent]:
        state = _StreamingState()
        completed = False
        try:
            async with client.stream(
                "POST",
                self._build_endpoint_url(),
                headers=self._build_headers(),
                json=self._build_request_body(request=request, stream=True),
                timeout=request.stream_timeout_seconds,
            ) as response:
                self._raise_for_status(response.status_code)
                async for line in response.aiter_lines():
                    payload_text = _parse_sse_data_line(line)
                    if payload_text is None:
                        continue
                    if payload_text == "[DONE]":
                        break

                    payload = _parse_json_text(payload_text)
                    usage = _extract_usage(_mapping_value(payload, "usage"))
                    if usage is not None:
                        state = _StreamingState(finish_reason=state.finish_reason, usage=usage)

                    choice = _first_choice(payload)
                    delta = _mapping_value(choice, "delta")
                    text = _extract_text(delta.get("content"))
                    if text:
                        yield ProviderLLMStreamEvent.delta(text=text)

                    finish_reason = _normalize_finish_reason(_string_value(choice, "finish_reason"))
                    if finish_reason is not None:
                        state = _StreamingState(finish_reason=finish_reason, usage=state.usage)
                        completed = True
                        yield ProviderLLMStreamEvent.completed(
                            finish_reason=finish_reason,
                            usage=state.usage,
                        )
        except httpx.TimeoutException as exc:
            raise LLMProviderTimeoutError(
                "OpenAI-compatible provider timed out.",
                metadata={"provider": self.name},
            ) from exc
        except httpx.TransportError as exc:
            raise LLMProviderUnavailableError(
                "OpenAI-compatible provider is unavailable.",
                metadata={"provider": self.name},
            ) from exc

        if not completed:
            yield ProviderLLMStreamEvent.completed(
                finish_reason=state.finish_reason,
                usage=state.usage,
            )

    async def _with_client(
        self,
        operation: Callable[[httpx.AsyncClient], Awaitable[httpx.Response]],
    ) -> httpx.Response:
        if self._client is not None:
            return await operation(self._client)

        async with httpx.AsyncClient() as client:
            return await operation(client)

    def _build_endpoint_url(self) -> str:
        base_url = self._provider.base_url
        if not base_url:
            raise LLMProviderUnavailableError(
                "OpenAI-compatible provider is missing a base URL.",
                metadata={"provider": self.name},
            )

        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or parsed.netloc == "":
            raise LLMProviderUnavailableError(
                "OpenAI-compatible provider base URL is invalid.",
                metadata={"provider": self.name},
            )

        normalized = base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        if normalized.endswith("/v1"):
            return f"{normalized}{_CHAT_COMPLETIONS_PATH}"
        return f"{normalized}/v1{_CHAT_COMPLETIONS_PATH}"

    def _build_headers(self) -> dict[str, str]:
        headers = dict(self._provider.headers)
        headers.setdefault("Accept", "application/json")
        auth_value = self._resolve_auth_value()
        if auth_value is not None:
            header_name, header_value = auth_value
            headers[header_name] = header_value
        return headers

    def _resolve_auth_value(self) -> tuple[str, str] | None:
        token = self._provider.auth_token or self._provider.api_key
        if token is None or token.strip() == "":
            return None

        header_name = self._provider.auth_header or "Authorization"
        if self._provider.auth_header is None:
            return header_name, f"Bearer {token}"
        return header_name, token

    def _build_request_body(
        self,
        *,
        request: ResolvedLLMRequest,
        stream: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [_serialize_message(message) for message in request.request.messages],
            "stream": stream,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens
        response_format = _serialize_response_format(request)
        if response_format is not None:
            body["response_format"] = response_format
        return body

    def _parse_json(self, response: httpx.Response) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise LLMMalformedResponseError(
                "OpenAI-compatible provider returned invalid JSON.",
                metadata={"provider": self.name},
            ) from exc
        if not isinstance(payload, Mapping):
            raise LLMMalformedResponseError(
                "OpenAI-compatible provider returned a non-object response.",
                metadata={"provider": self.name},
            )
        return cast(Mapping[str, Any], payload)

    def _raise_for_status(self, status_code: int) -> None:
        metadata = {"provider": self.name, "status_code": status_code}
        if status_code < 400:
            return
        if status_code in {401, 403}:
            raise LLMAuthenticationError("OpenAI-compatible provider rejected authentication.", metadata=metadata)
        if status_code == 408 or status_code == 504:
            raise LLMProviderTimeoutError("OpenAI-compatible provider timed out.", metadata=metadata)
        if status_code == 429:
            raise LLMRateLimitError("OpenAI-compatible provider rate limited the request.", metadata=metadata)
        if 400 <= status_code < 500:
            raise LLMBadRequestError("OpenAI-compatible provider rejected the request.", metadata=metadata)
        raise LLMProviderUnavailableError("OpenAI-compatible provider is unavailable.", metadata=metadata)


def _serialize_message(message: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role}
    if message.name:
        payload["name"] = message.name
    payload["content"] = _serialize_content(message.content)
    return payload


def _serialize_content(content: str | Sequence[LLMContentPart]) -> Any:
    if isinstance(content, str):
        return content

    parts: list[dict[str, Any]] = []
    for part in content:
        if part.type == "text":
            parts.append({"type": "text", "text": part.text or ""})
            continue
        if part.type == "image_url":
            parts.append({"type": "image_url", "image_url": {"url": part.image_url or ""}})
            continue
        parts.append(
            {
                "type": "text",
                "text": json.dumps(part.json_value, ensure_ascii=True, separators=(",", ":")),
            }
        )
    return parts


def _serialize_response_format(request: ResolvedLLMRequest) -> dict[str, Any] | None:
    response_format = request.response_format
    if response_format is None or response_format.type == "text":
        return None
    if response_format.type == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": response_format.schema_name or "response",
            "schema": dict(response_format.json_schema or {}),
            "strict": response_format.strict,
        },
    }


def _parse_sse_data_line(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(":"):
        return None
    if not stripped.startswith("data:"):
        return None
    return stripped[5:].strip()


def _parse_json_text(payload_text: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(payload_text)
    except ValueError as exc:
        raise LLMMalformedResponseError("OpenAI-compatible stream returned invalid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise LLMMalformedResponseError("OpenAI-compatible stream returned a non-object payload.")
    return cast(Mapping[str, Any], payload)


def _first_choice(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, Sequence) or not choices:
        raise LLMMalformedResponseError("OpenAI-compatible provider returned no choices.")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise LLMMalformedResponseError("OpenAI-compatible provider returned a malformed choice.")
    return cast(Mapping[str, Any], first)


def _extract_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, Sequence):
        return None

    text_parts: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            direct_text = item.get("text")
            if isinstance(direct_text, str):
                text_parts.append(direct_text)
                continue
            if isinstance(direct_text, Mapping):
                nested_value = direct_text.get("value")
                if isinstance(nested_value, str):
                    text_parts.append(nested_value)
                    continue
            item_type = item.get("type")
            if item_type == "output_text":
                nested_text = item.get("text")
                if isinstance(nested_text, str):
                    text_parts.append(nested_text)
    if not text_parts:
        return None
    return "".join(text_parts)


def _extract_usage(value: object) -> LLMTokenUsage | None:
    if not isinstance(value, Mapping):
        return None
    input_tokens = _read_optional_int(value.get("prompt_tokens"))
    if input_tokens is None:
        input_tokens = _read_optional_int(value.get("input_tokens"))
    output_tokens = _read_optional_int(value.get("completion_tokens"))
    if output_tokens is None:
        output_tokens = _read_optional_int(value.get("output_tokens"))
    total_tokens = _read_optional_int(value.get("total_tokens"))
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    return LLMTokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        raw=dict(value),
    )


def _normalize_finish_reason(value: str | None) -> str | None:
    if value is None:
        return None
    return _FINISH_REASON_MAP.get(value, value)


def _safe_response_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    response_id = payload.get("id")
    if isinstance(response_id, str):
        metadata["response_id"] = response_id
    model_name = payload.get("model")
    if isinstance(model_name, str):
        metadata["model"] = model_name
    return metadata


def _mapping_value(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    return {}


def _string_value(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return None


def _read_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None