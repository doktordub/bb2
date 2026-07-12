"""Normalized agent-layer errors and safe error details."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.contracts.errors import (
    ConfigurationError,
    GatewayError,
    LLMGatewayError,
    MemoryGatewayError,
    PolicyDeniedError,
    ToolGatewayError,
)
from app.orchestration.models import sanitize_metadata


@dataclass(frozen=True, slots=True)
class AgentErrorDetail:
    """Safe error detail emitted across the agent boundary."""

    code: str
    message: str
    retryable: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _normalize_identifier(self.code, field_name="code"))
        object.__setattr__(
            self,
            "message",
            _normalize_safe_message(self.message, fallback=AgentError.default_message),
        )
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


class AgentError(Exception):
    """Base class for structured agent failures."""

    code = "agent_error"
    default_message = "The agent request failed."
    default_retryable = False

    def __init__(
        self,
        message: str | None = None,
        *,
        retryable: bool | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.message = _normalize_safe_message(message, fallback=self.default_message)
        self.retryable = self.default_retryable if retryable is None else bool(retryable)
        self.metadata = sanitize_metadata(metadata)
        super().__init__(self.message)

    def to_detail(self) -> AgentErrorDetail:
        return AgentErrorDetail(
            code=self.code,
            message=self.message,
            retryable=self.retryable,
            metadata=self.metadata,
        )


class AgentNotFoundError(AgentError):
    code = "agent_not_found"
    default_message = "The selected agent is not available."


class AgentDisabledError(AgentError):
    code = "agent_disabled"
    default_message = "The selected agent is disabled."


class AgentConfigurationError(AgentError):
    code = "agent_configuration_error"
    default_message = "The agent configuration is invalid."


class AgentPolicyDeniedError(AgentError):
    code = "agent_policy_denied"
    default_message = "The request was denied by agent policy."


class AgentCapabilityError(AgentError):
    code = "agent_capability_error"
    default_message = "The agent does not support the requested capability."


class AgentInputValidationError(AgentError):
    code = "agent_input_invalid"
    default_message = "The agent request is invalid."


class AgentPromptBuildError(AgentError):
    code = "agent_prompt_build_error"
    default_message = "The agent prompt could not be built safely."


class AgentLLMError(AgentError):
    code = "agent_llm_error"
    default_message = "The agent LLM request failed."
    default_retryable = True


class AgentOutputParseError(AgentError):
    code = "agent_output_parse_error"
    default_message = "The agent output could not be parsed safely."


class AgentToolIntentError(AgentError):
    code = "agent_tool_intent_error"
    default_message = "The agent produced an invalid tool intent."


class AgentMemoryCandidateError(AgentError):
    code = "agent_memory_candidate_error"
    default_message = "The agent produced an invalid memory candidate."


class AgentReviewError(AgentError):
    code = "agent_review_error"
    default_message = "The agent review step failed."


class AgentLimitExceededError(AgentError):
    code = "agent_limit_exceeded"
    default_message = "The agent exceeded its configured limits."


class AgentCancelledError(AgentError):
    code = "agent_cancelled"
    default_message = "The agent request was cancelled."


def normalize_agent_error(error: BaseException) -> AgentError:
    """Convert arbitrary exceptions into stable agent errors."""

    if isinstance(error, AgentError):
        return error
    if isinstance(error, asyncio.CancelledError):
        return AgentCancelledError()
    if isinstance(error, PolicyDeniedError):
        return AgentPolicyDeniedError(
            str(error),
            retryable=_error_retryable(error),
            metadata=_error_metadata(
                error,
                source_error_code=_error_source_code(error),
                policy_denied=True,
            ),
        )
    source_error_code = _error_source_code(error)
    if source_error_code is not None and source_error_code.endswith("_policy_denied"):
        return AgentPolicyDeniedError(
            str(error),
            retryable=_error_retryable(error),
            metadata=_error_metadata(
                error,
                source_error_code=source_error_code,
                policy_denied=True,
            ),
        )
    if isinstance(error, ConfigurationError):
        return AgentConfigurationError()
    if isinstance(error, LLMGatewayError):
        return AgentLLMError(retryable=True)
    if isinstance(error, ToolGatewayError):
        return AgentToolIntentError()
    if isinstance(error, MemoryGatewayError):
        return AgentMemoryCandidateError()
    if isinstance(error, GatewayError):
        return AgentLLMError(retryable=True)
    return AgentError()


def error_detail_from_exception(error: BaseException) -> AgentErrorDetail:
    """Return a safe detail for streaming and result boundaries."""

    return normalize_agent_error(error).to_detail()


def agent_error_from_detail(detail: AgentErrorDetail) -> AgentError:
    """Rebuild a normalized agent error from a safe detail payload."""

    error_type = _ERROR_TYPES_BY_CODE.get(detail.code, AgentError)
    return error_type(detail.message, retryable=detail.retryable, metadata=detail.metadata)


_ERROR_TYPES_BY_CODE: dict[str, type[AgentError]] = {
    AgentNotFoundError.code: AgentNotFoundError,
    AgentDisabledError.code: AgentDisabledError,
    AgentConfigurationError.code: AgentConfigurationError,
    AgentPolicyDeniedError.code: AgentPolicyDeniedError,
    AgentCapabilityError.code: AgentCapabilityError,
    AgentInputValidationError.code: AgentInputValidationError,
    AgentPromptBuildError.code: AgentPromptBuildError,
    AgentLLMError.code: AgentLLMError,
    AgentOutputParseError.code: AgentOutputParseError,
    AgentToolIntentError.code: AgentToolIntentError,
    AgentMemoryCandidateError.code: AgentMemoryCandidateError,
    AgentReviewError.code: AgentReviewError,
    AgentLimitExceededError.code: AgentLimitExceededError,
    AgentCancelledError.code: AgentCancelledError,
}


def _normalize_identifier(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"Invalid {field_name}.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"Invalid {field_name}.")
    return normalized


def _normalize_safe_message(value: object, *, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    if not normalized:
        return fallback
    lowered = normalized.casefold()
    if "traceback" in lowered or "stack trace" in lowered or 'file "' in lowered:
        return fallback
    return normalized if len(normalized) <= 400 else normalized[:399].rstrip() + "..."


def _error_source_code(error: BaseException) -> str | None:
    code = getattr(error, "code", None)
    if not isinstance(code, str):
        return None
    normalized = code.strip()
    return normalized or None


def _error_retryable(error: BaseException) -> bool | None:
    retryable = getattr(error, "retryable", None)
    if isinstance(retryable, bool):
        return retryable
    return None


def _error_metadata(
    error: BaseException,
    *,
    source_error_code: str | None = None,
    policy_denied: bool = False,
) -> dict[str, Any]:
    raw_metadata = getattr(error, "metadata", None)
    metadata = sanitize_metadata(raw_metadata if isinstance(raw_metadata, Mapping) else None)
    if source_error_code is not None:
        metadata.setdefault("source_error_code", source_error_code)
    if policy_denied:
        metadata["policy_denied"] = True
        summary = _policy_block_summary(str(error))
        if summary is not None:
            metadata.setdefault("policy_block_summary", summary)
    return metadata


def _policy_block_summary(message: str | None) -> str | None:
    if not isinstance(message, str):
        return None
    normalized = message.strip()
    if not normalized:
        return None
    return _normalize_safe_message(normalized, fallback=AgentPolicyDeniedError.default_message)


__all__ = [
    "AgentCancelledError",
    "AgentCapabilityError",
    "AgentConfigurationError",
    "AgentDisabledError",
    "AgentError",
    "AgentErrorDetail",
    "AgentInputValidationError",
    "AgentLLMError",
    "AgentLimitExceededError",
    "AgentMemoryCandidateError",
    "AgentNotFoundError",
    "AgentOutputParseError",
    "AgentPolicyDeniedError",
    "AgentPromptBuildError",
    "AgentReviewError",
    "AgentToolIntentError",
    "agent_error_from_detail",
    "error_detail_from_exception",
    "normalize_agent_error",
]