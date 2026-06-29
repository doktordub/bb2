"""Normalized orchestration error types and safe error details."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.contracts.errors import ConfigurationError, GatewayError, PolicyDeniedError
from app.orchestration.models import sanitize_metadata


@dataclass(frozen=True, slots=True)
class OrchestrationErrorDetail:
    """Safe error envelope emitted by orchestration boundaries."""

    code: str
    message: str
    retryable: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _normalize_identifier(self.code, field_name="code"))
        object.__setattr__(self, "message", _normalize_safe_message(self.message, fallback="The request failed."))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


class OrchestrationError(Exception):
    """Base class for normalized orchestration failures."""

    code = "orchestration_error"
    default_message = "The orchestration request failed."
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

    def to_detail(self) -> OrchestrationErrorDetail:
        return OrchestrationErrorDetail(
            code=self.code,
            message=self.message,
            retryable=self.retryable,
            metadata=self.metadata,
        )


class OrchestrationDisabledError(OrchestrationError):
    code = "orchestration_disabled"
    default_message = "Orchestration is not available."


class UnknownUseCaseError(OrchestrationError):
    code = "unknown_usecase"
    default_message = "The requested use case is not available."


class StrategyNotFoundError(OrchestrationError):
    code = "strategy_not_found"
    default_message = "The requested orchestration strategy is not available."


class StrategyDisabledError(OrchestrationError):
    code = "strategy_disabled"
    default_message = "The selected orchestration strategy is disabled."


class StrategyPolicyDeniedError(OrchestrationError):
    code = "strategy_policy_denied"
    default_message = "The request was denied by orchestration policy."


class StrategyFallbackNotAllowedError(OrchestrationError):
    code = "strategy_fallback_not_allowed"
    default_message = "The strategy fallback path is not allowed."


class AgentNotFoundError(OrchestrationError):
    code = "agent_not_found"
    default_message = "The selected agent is not available."


class AgentExecutionError(OrchestrationError):
    code = "agent_execution_failed"
    default_message = "The agent could not complete the request."
    default_retryable = True


class OrchestrationLimitExceededError(OrchestrationError):
    code = "orchestration_limit_exceeded"
    default_message = "The request exceeded orchestration limits."


class OrchestrationTimeoutError(OrchestrationError):
    code = "orchestration_timeout"
    default_message = "The orchestration request timed out."
    default_retryable = True


class OrchestrationCancelledError(OrchestrationError):
    code = "orchestration_cancelled"
    default_message = "The orchestration request was cancelled."


class OrchestrationDependencyUnavailableError(OrchestrationError):
    code = "dependency_unavailable"
    default_message = "A required orchestration dependency is unavailable."
    default_retryable = True


class OrchestrationMalformedOutputError(OrchestrationError):
    code = "malformed_orchestration_output"
    default_message = "The orchestration result could not be normalized safely."


class OrchestrationPlanValidationError(OrchestrationError):
    code = "strategy_plan_invalid"
    default_message = "The planner returned an invalid bounded plan."


class OrchestrationIntentValidationError(OrchestrationError):
    code = "orchestration_intent_invalid"
    default_message = "The orchestration request contained an invalid tool or memory intent."


class OrchestrationContextBudgetExceededError(OrchestrationError):
    code = "orchestration_context_budget_exceeded"
    default_message = "The orchestration context exceeded the configured budget."


def normalize_orchestration_error(error: BaseException) -> OrchestrationError:
    """Coerce arbitrary exceptions into stable orchestration errors."""

    if isinstance(error, OrchestrationError):
        return error
    if isinstance(error, asyncio.CancelledError):
        return OrchestrationCancelledError()
    if isinstance(error, TimeoutError):
        return OrchestrationTimeoutError()
    if isinstance(error, PolicyDeniedError):
        return StrategyPolicyDeniedError()
    if isinstance(error, ConfigurationError):
        return OrchestrationDisabledError()
    if isinstance(error, GatewayError):
        return OrchestrationDependencyUnavailableError()
    return AgentExecutionError()


def error_detail_from_exception(error: BaseException) -> OrchestrationErrorDetail:
    """Return a safe error detail for stream and result boundaries."""

    return normalize_orchestration_error(error).to_detail()


def orchestration_error_from_detail(detail: OrchestrationErrorDetail) -> OrchestrationError:
    """Rebuild a normalized orchestration error from a safe error detail."""

    error_type = _ERROR_TYPES_BY_CODE.get(detail.code, AgentExecutionError)
    return error_type(detail.message, retryable=detail.retryable, metadata=detail.metadata)


_ERROR_TYPES_BY_CODE: dict[str, type[OrchestrationError]] = {
    OrchestrationDisabledError.code: OrchestrationDisabledError,
    UnknownUseCaseError.code: UnknownUseCaseError,
    StrategyNotFoundError.code: StrategyNotFoundError,
    StrategyDisabledError.code: StrategyDisabledError,
    StrategyPolicyDeniedError.code: StrategyPolicyDeniedError,
    StrategyFallbackNotAllowedError.code: StrategyFallbackNotAllowedError,
    AgentNotFoundError.code: AgentNotFoundError,
    AgentExecutionError.code: AgentExecutionError,
    OrchestrationLimitExceededError.code: OrchestrationLimitExceededError,
    OrchestrationTimeoutError.code: OrchestrationTimeoutError,
    OrchestrationCancelledError.code: OrchestrationCancelledError,
    OrchestrationDependencyUnavailableError.code: OrchestrationDependencyUnavailableError,
    OrchestrationMalformedOutputError.code: OrchestrationMalformedOutputError,
    OrchestrationPlanValidationError.code: OrchestrationPlanValidationError,
    OrchestrationIntentValidationError.code: OrchestrationIntentValidationError,
    OrchestrationContextBudgetExceededError.code: OrchestrationContextBudgetExceededError,
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
    if "traceback" in lowered or "stack trace" in lowered or "file \"" in lowered:
        return fallback
    if len(normalized) <= 400:
        return normalized
    return normalized[:399].rstrip() + "..."