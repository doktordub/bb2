"""Approximate request budget checks for the concrete LLM gateway."""

from __future__ import annotations

import json

from app.contracts.llm import LLMContentPart, LLMMessage
from app.llm.errors import LLMBadRequestError, LLMContextLengthError
from app.llm.models import ResolvedLLMRequest


def enforce_token_budget(resolved: ResolvedLLMRequest) -> dict[str, int | None]:
    """Reject requests that exceed configured profile token limits."""

    estimated_input_tokens = estimate_request_tokens(resolved.request.messages)
    requested_output_tokens = resolved.max_output_tokens

    max_input_tokens = resolved.profile.max_input_tokens
    if max_input_tokens is not None and estimated_input_tokens > max_input_tokens:
        raise LLMContextLengthError(
            f"LLM request exceeds the max_input_tokens for profile '{resolved.profile_name}'.",
            metadata={
                "profile": resolved.profile_name,
                "estimated_input_tokens": estimated_input_tokens,
                "max_input_tokens": max_input_tokens,
            },
        )

    profile_output_limit = resolved.profile.max_output_tokens
    if (
        requested_output_tokens is not None
        and profile_output_limit is not None
        and requested_output_tokens > profile_output_limit
    ):
        raise LLMBadRequestError(
            f"Requested output exceeds the max_output_tokens for profile '{resolved.profile_name}'.",
            metadata={
                "profile": resolved.profile_name,
                "requested_output_tokens": requested_output_tokens,
                "max_output_tokens": profile_output_limit,
            },
        )

    max_total_tokens = resolved.profile.max_total_tokens
    if (
        max_total_tokens is not None
        and requested_output_tokens is not None
        and estimated_input_tokens + requested_output_tokens > max_total_tokens
    ):
        raise LLMContextLengthError(
            f"LLM request exceeds the max_total_tokens for profile '{resolved.profile_name}'.",
            metadata={
                "profile": resolved.profile_name,
                "estimated_input_tokens": estimated_input_tokens,
                "requested_output_tokens": requested_output_tokens,
                "max_total_tokens": max_total_tokens,
            },
        )

    return {
        "estimated_input_tokens": estimated_input_tokens,
        "requested_output_tokens": requested_output_tokens,
    }


def estimate_request_tokens(messages: list[LLMMessage]) -> int:
    total = 0
    for message in messages:
        total += 1
        total += _estimate_message_tokens(message)
    return total


def _estimate_message_tokens(message: LLMMessage) -> int:
    if isinstance(message.content, str):
        return _estimate_text_tokens(message.content)

    total = 0
    for part in message.content:
        total += _estimate_content_part_tokens(part)
    return total


def _estimate_content_part_tokens(part: LLMContentPart) -> int:
    if part.text is not None:
        return _estimate_text_tokens(part.text)
    if part.image_url is not None:
        return _estimate_text_tokens(part.image_url)
    if part.json_value is not None:
        return _estimate_text_tokens(json.dumps(part.json_value, sort_keys=True))
    return 0


def _estimate_text_tokens(value: str) -> int:
    return max(len(value.split()), 1) if value else 0