"""Compatibility shim that re-exports the phase-4 orchestration runtime surface."""

from app.orchestration.runtime import (
    DefaultOrchestrationRuntime,
    DirectAgentOrchestrationRuntime,
    EchoOrchestrationRuntime,
    OrchestrationRuntime,
)
from app.orchestration.strategy_factory import build_strategy_registry

__all__ = [
    "DefaultOrchestrationRuntime",
    "DirectAgentOrchestrationRuntime",
    "EchoOrchestrationRuntime",
    "OrchestrationRuntime",
    "build_strategy_registry",
]
