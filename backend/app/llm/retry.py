"""Retry and error-classification helpers for the concrete LLM gateway."""

from __future__ import annotations

import asyncio

from app.llm.errors import (
    LLMBadRequestError,
    LLMCancelledError,
    LLMMalformedResponseError,
    LLMProviderTimeoutError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMRuntimeError,
    LLMStreamingError,
)


def normalize_runtime_error(error: BaseException, *, streaming: bool = False) -> LLMRuntimeError:
    """Normalize arbitrary provider failures into stable runtime errors."""

    if isinstance(error, LLMRuntimeError):
        return error
    if isinstance(error, asyncio.CancelledError):
        return LLMCancelledError("LLM operation was cancelled.")
    if isinstance(error, TimeoutError):
        return LLMProviderTimeoutError("LLM provider timed out.")
    if isinstance(error, ConnectionError):
        return LLMProviderUnavailableError("LLM provider is unavailable.")
    if isinstance(error, ValueError):
        return LLMBadRequestError(str(error) or "LLM provider rejected the request.")
    if streaming:
        return LLMStreamingError(
            "LLM streaming failed.",
            metadata={"error_type": type(error).__name__},
        )
    return LLMMalformedResponseError(
        "LLM provider returned an unexpected response.",
        metadata={"error_type": type(error).__name__},
    )


def is_retryable_error(error: LLMRuntimeError) -> bool:
    return bool(error.retryable)


def is_fallback_eligible(error: LLMRuntimeError) -> bool:
    return isinstance(
        error,
        (
            LLMProviderUnavailableError,
            LLMProviderTimeoutError,
            LLMRateLimitError,
            LLMStreamingError,
        ),
    )