"""Trace-safe summaries for LLM requests and responses."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.contracts.llm import LLMContentPart, LLMRequest, LLMResponse, LLMTokenUsage
from app.llm.errors import LLMRuntimeError
from app.llm.models import ProviderLLMResponse, ResolvedLLMRequest


def summarize_request(request: LLMRequest, *, resolved: ResolvedLLMRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "component": resolved.component,
        "profile": resolved.profile_name,
        "provider": resolved.provider_name,
        "model": resolved.model,
        "stream": request.stream,
        "message_count": len(request.messages),
        "message_roles": tuple(message.role for message in request.messages),
        "has_structured_content": any(isinstance(message.content, list) for message in request.messages),
        "response_format": None if resolved.response_format is None else resolved.response_format.type,
        "timeout_seconds": resolved.timeout_seconds,
        "max_output_tokens": resolved.max_output_tokens,
        "resolution_source": resolved.resolution_source,
    }
    if resolved.trace_prompts:
        payload["messages"] = [_message_summary(message.content) for message in request.messages]
    return payload


def summarize_provider_response(
    response: ProviderLLMResponse | LLMResponse,
    *,
    include_text: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "finish_reason": response.finish_reason,
        "usage": _usage_summary(response.usage),
        "raw_id_present": response.raw_id is not None,
    }
    if include_text:
        payload["text"] = response.text
    return payload


def summarize_error(error: LLMRuntimeError) -> dict[str, Any]:
    return {
        "error_type": type(error).__name__,
        "error_code": error.code,
        "retryable": error.retryable,
        "metadata": dict(error.metadata),
    }


def _message_summary(content: str | list[LLMContentPart]) -> Mapping[str, Any] | str:
    if isinstance(content, str):
        return content
    return {
        "part_count": len(content),
        "part_types": tuple(getattr(part, "type", type(part).__name__) for part in content),
    }


def _usage_summary(usage: LLMTokenUsage | None) -> dict[str, int | None] | None:
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }