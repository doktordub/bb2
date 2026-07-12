"""Trace-safe summaries for LLM requests and responses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.contracts.llm import LLMContentPart, LLMMessage, LLMRequest, LLMResponse, LLMTokenUsage, LLMToolCall
from app.llm.errors import LLMRuntimeError
from app.llm.models import ProviderLLMResponse, ResolvedLLMRequest


def summarize_request(request: LLMRequest, *, resolved: ResolvedLLMRequest) -> dict[str, Any]:
    assistant_tool_call_count = sum(
        len(message.tool_calls)
        for message in request.messages
        if message.role == "assistant"
    )
    tool_result_message_count = sum(1 for message in request.messages if message.role == "tool")
    payload: dict[str, Any] = {
        "component": resolved.component,
        "profile": resolved.profile_name,
        "provider": resolved.provider_name,
        "model": resolved.model,
        "stream": request.stream,
        "message_count": len(request.messages),
        "message_roles": tuple(message.role for message in request.messages),
        "has_structured_content": any(isinstance(message.content, list) for message in request.messages),
        "tool_count": len(request.tools),
        "tool_names": _tool_call_names(request.tools),
        "tool_choice_mode": None if request.tool_choice is None else request.tool_choice.type,
        "tool_choice_name": _tool_choice_name(request),
        "has_assistant_tool_calls": assistant_tool_call_count > 0,
        "assistant_tool_call_count": assistant_tool_call_count,
        "has_tool_result_messages": tool_result_message_count > 0,
        "tool_result_message_count": tool_result_message_count,
        "response_format": None if resolved.response_format is None else resolved.response_format.type,
        "timeout_seconds": resolved.timeout_seconds,
        "max_output_tokens": resolved.max_output_tokens,
        "resolution_source": resolved.resolution_source,
    }
    if resolved.trace_prompts:
        payload["messages"] = [_message_summary(message) for message in request.messages]
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
        "tool_call_count": len(response.tool_calls),
        "tool_call_names": _tool_call_names(response.tool_calls),
        "text_present": bool(response.text),
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


def _message_summary(message: LLMMessage) -> Mapping[str, Any] | str:
    content_summary = _content_summary(message.content)
    if (
        isinstance(content_summary, str)
        and message.name is None
        and message.tool_call_id is None
        and not message.tool_calls
    ):
        return content_summary

    payload: dict[str, Any] = {
        "role": message.role,
        "content": content_summary,
    }
    if message.name is not None:
        payload["name"] = message.name
    if message.tool_call_id is not None:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": tool_call.type,
                "function_name": tool_call.function.name,
            }
            for tool_call in message.tool_calls
        ]
    return payload


def _content_summary(content: str | list[LLMContentPart]) -> Mapping[str, Any] | str:
    if isinstance(content, str):
        return content
    return {
        "part_count": len(content),
        "part_types": tuple(getattr(part, "type", type(part).__name__) for part in content),
    }


def _tool_call_names(tool_entries: Sequence[Any]) -> tuple[str, ...]:
    names: list[str] = []
    for entry in tool_entries:
        name = _tool_entry_name(entry)
        if name is not None:
            names.append(name)
    return tuple(names)


def _tool_entry_name(entry: Any) -> str | None:
    function = getattr(entry, "function", None)
    name = getattr(function, "name", None)
    if isinstance(name, str):
        normalized = name.strip()
        if normalized:
            return normalized
    return None


def _tool_choice_name(request: LLMRequest) -> str | None:
    if request.tool_choice is None or request.tool_choice.function is None:
        return None
    name = request.tool_choice.function.name
    normalized = name.strip()
    return normalized or None


def _usage_summary(usage: LLMTokenUsage | None) -> dict[str, int | None] | None:
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
    }