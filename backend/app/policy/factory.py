"""Composition helpers for the concrete backend policy runtime."""

from __future__ import annotations

from dataclasses import dataclass

from app.config.view import get_policy_settings
from app.contracts.config import ConfigurationView
from app.observability.metrics import MetricsRecorder, NoopMetricsRecorder
from app.policy.engine import DefaultPolicyEngine
from app.policy.registry import PolicyRegistry
from app.policy.rule_loader import load_default_policy_registry
from app.policy.service import DefaultPolicyService
from app.policy.settings import PolicySettings


@dataclass(frozen=True, slots=True)
class PolicyRuntimeBundle:
    """Composed policy runtime services for startup wiring and tests."""

    settings: PolicySettings
    registry: PolicyRegistry
    engine: DefaultPolicyEngine
    service: DefaultPolicyService


def build_policy_runtime(
    config: ConfigurationView,
    *,
    metrics: MetricsRecorder | None = None,
) -> PolicyRuntimeBundle:
    """Build the concrete policy runtime from validated backend configuration."""

    settings = get_policy_settings(config)
    registry = load_default_policy_registry()
    engine = DefaultPolicyEngine(config=config, settings=settings, registry=registry)
    service = DefaultPolicyService(
        config,
        engine=engine,
        metrics=metrics or NoopMetricsRecorder(),
    )
    return PolicyRuntimeBundle(
        settings=settings,
        registry=registry,
        engine=engine,
        service=service,
    )