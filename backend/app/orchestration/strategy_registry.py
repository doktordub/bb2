"""Strategy registration and lookup helpers for orchestration runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config.view import StrategySettings
from app.orchestration.errors import StrategyDisabledError, StrategyNotFoundError
from app.orchestration.models import sanitize_metadata
from app.orchestration.strategy import OrchestrationStrategy


@dataclass(frozen=True, slots=True)
class StrategyDescriptor:
    """Safe strategy summary suitable for health and capability reporting."""

    name: str
    type: str
    enabled: bool
    allowed_usecases: tuple[str, ...]
    default_agent: str | None = None
    llm_profile: str | None = None
    description: str | None = None
    memory_enabled: bool = False
    memory_write_enabled: bool = False
    tools_enabled: bool = False
    streaming_supported: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class ResolvedStrategy:
    """Resolved runtime strategy plus the settings that selected it."""

    strategy: OrchestrationStrategy
    settings: StrategySettings
    source: str


@dataclass(frozen=True, slots=True)
class _RegistryEntry:
    strategy: OrchestrationStrategy
    settings: StrategySettings


class StrategyRegistry:
    """Minimal strategy registry used by the phase-3 orchestration runtime."""

    def __init__(self) -> None:
        self._entries: dict[str, _RegistryEntry] = {}

    def register(self, strategy: OrchestrationStrategy, settings: StrategySettings) -> None:
        name = _normalize_name(settings.name)
        if name in self._entries:
            raise ValueError(f"Strategy '{name}' is already registered.")
        self._entries[name] = _RegistryEntry(strategy=strategy, settings=settings)

    def resolve(
        self,
        *,
        strategy_name: str,
        usecase: str | None,
        source: str = "configured",
    ) -> ResolvedStrategy:
        name = _normalize_name(strategy_name)
        entry = self._entries.get(name)
        if entry is None:
            raise StrategyNotFoundError(f"Strategy '{name}' is not registered in this runtime.")

        if not entry.settings.enabled:
            raise StrategyDisabledError(f"Strategy '{name}' is disabled.")

        allowed_usecases = entry.settings.allowed_usecases
        if allowed_usecases and usecase not in allowed_usecases:
            raise StrategyNotFoundError(
                f"Strategy '{name}' is not allowed for use case '{usecase or 'unknown'}'."
            )

        return ResolvedStrategy(
            strategy=entry.strategy,
            settings=entry.settings,
            source=source,
        )

    def list(self, *, enabled_only: bool = True) -> list[StrategyDescriptor]:
        descriptors: list[StrategyDescriptor] = []
        for name, entry in sorted(self._entries.items()):
            if enabled_only and not entry.settings.enabled:
                continue
            descriptors.append(
                StrategyDescriptor(
                    name=name,
                    type=entry.settings.type,
                    enabled=entry.settings.enabled,
                    allowed_usecases=entry.settings.allowed_usecases,
                    default_agent=entry.settings.default_agent,
                    llm_profile=entry.settings.llm_profile,
                    description=entry.settings.description,
                    memory_enabled=entry.settings.memory_enabled,
                    memory_write_enabled=entry.settings.memory_write_enabled,
                    tools_enabled=entry.settings.tools_enabled,
                    streaming_supported=_streaming_supported(entry.settings),
                    metadata=entry.settings.metadata,
                )
            )
        return descriptors


def _normalize_name(value: object) -> str:
    if not isinstance(value, str):
        raise StrategyNotFoundError("Strategy name is required.")
    normalized = value.strip()
    if not normalized:
        raise StrategyNotFoundError("Strategy name is required.")
    return normalized


def _streaming_supported(settings: StrategySettings) -> bool:
    return settings.type in {
        "echo",
        "direct_agent",
        "retrieval_augmented",
        "tool_assisted",
        "router",
        "bounded_planner",
        "memory_update",
        "fallback_answer",
    }