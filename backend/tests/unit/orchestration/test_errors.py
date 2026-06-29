from __future__ import annotations

import asyncio

from app.contracts.errors import ConfigurationError, LLMGatewayError, PolicyDeniedError
from app.orchestration.errors import (
    AgentExecutionError,
    OrchestrationCancelledError,
    OrchestrationErrorDetail,
    OrchestrationDependencyUnavailableError,
    OrchestrationDisabledError,
    OrchestrationIntentValidationError,
    OrchestrationTimeoutError,
    StrategyPolicyDeniedError,
    UnknownUseCaseError,
    normalize_orchestration_error,
    orchestration_error_from_detail,
)


def test_error_types_expose_stable_codes_and_retryability() -> None:
    cases = [
        (OrchestrationDisabledError(), "orchestration_disabled", False),
        (UnknownUseCaseError(), "unknown_usecase", False),
        (AgentExecutionError(), "agent_execution_failed", True),
        (OrchestrationTimeoutError(), "orchestration_timeout", True),
        (OrchestrationCancelledError(), "orchestration_cancelled", False),
        (OrchestrationDependencyUnavailableError(), "dependency_unavailable", True),
    ]

    for error, code, retryable in cases:
        detail = error.to_detail()
        assert detail.code == code
        assert detail.retryable is retryable


def test_normalize_orchestration_error_maps_known_error_families() -> None:
    assert isinstance(normalize_orchestration_error(ConfigurationError("bad")), OrchestrationDisabledError)
    assert isinstance(normalize_orchestration_error(PolicyDeniedError("no")), StrategyPolicyDeniedError)
    assert isinstance(normalize_orchestration_error(LLMGatewayError("down")), OrchestrationDependencyUnavailableError)
    assert isinstance(normalize_orchestration_error(asyncio.CancelledError()), OrchestrationCancelledError)


def test_generic_errors_are_normalized_to_safe_agent_failures() -> None:
    error = normalize_orchestration_error(RuntimeError("Traceback: raw provider detail"))

    assert isinstance(error, AgentExecutionError)
    assert error.message == "The agent could not complete the request."


def test_error_detail_round_trip_rebuilds_known_error_types() -> None:
    detail = OrchestrationErrorDetail(
        code="orchestration_intent_invalid",
        message="Bad tool intent.",
        retryable=False,
    )

    error = orchestration_error_from_detail(detail)

    assert isinstance(error, OrchestrationIntentValidationError)
    assert error.message == "Bad tool intent."