"""Policy-specific runtime and configuration errors."""

from __future__ import annotations

from app.contracts.errors import ConfigurationError


class PolicyConfigurationError(ConfigurationError):
    """Policy configuration is missing, invalid, or inconsistent."""


class PolicyEvaluationError(RuntimeError):
    """Policy evaluation could not complete safely."""


class PolicyInvariantError(PolicyEvaluationError):
    """Policy runtime invariants were violated during evaluation."""