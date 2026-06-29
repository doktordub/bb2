"""Internal models used by the concrete LLM runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from app.config.view import LLMDefaultsSettings, LLMProfileSettings, LLMProviderSettings
from app.contracts.llm import LLMRequest, LLMResponseFormat, LLMTokenUsage

ProviderStreamEventType = Literal["started", "delta", "metadata", "completed", "error"]


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Safe capability summary for one concrete provider adapter."""

    provider_name: str
    provider_type: str
    supports_streaming: bool = True
    supports_json_schema: bool = False
    supports_tool_calling: bool = False


@dataclass(frozen=True, slots=True)
class ProviderHealthSummary:
    """Provider-owned health data before it is mapped to public contracts."""

    provider_name: str
    provider_type: str
    status: str
    enabled: bool
    available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProfileHealthSummary:
    """Gateway-owned health data for one logical profile."""

    profile_name: str
    provider_name: str
    status: str
    enabled: bool
    supports_streaming: bool
    supports_json_schema: bool
    supports_tool_calling: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResolvedLLMRequest:
    """LLM request after logical profile resolution and runtime defaulting."""

    request: LLMRequest
    defaults: LLMDefaultsSettings
    provider: LLMProviderSettings
    profile: LLMProfileSettings
    profile_name: str
    provider_name: str
    model: str
    timeout_seconds: int
    stream_timeout_seconds: int
    max_retries: int
    response_format: LLMResponseFormat | None
    max_output_tokens: int | None
    agent_name: str | None = None
    strategy_name: str | None = None
    usecase_name: str | None = None
    resolution_source: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def component(self) -> str:
        return self.request.component or "llm.gateway"

    @property
    def temperature(self) -> float | None:
        if self.request.temperature is not None:
            return self.request.temperature
        return self.profile.temperature

    @property
    def top_p(self) -> float | None:
        if self.request.top_p is not None:
            return self.request.top_p
        return self.profile.top_p

    @property
    def stream(self) -> bool:
        return self.request.stream

    @property
    def trace_prompts(self) -> bool:
        return self.defaults.trace_prompts

    @property
    def trace_completions(self) -> bool:
        return self.defaults.trace_completions


@dataclass(frozen=True, slots=True)
class ProviderLLMResponse:
    """Provider-native completion data after adapter normalization."""

    text: str
    finish_reason: str | None = None
    usage: LLMTokenUsage | None = None
    raw_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderLLMStreamEvent:
    """Provider-native stream event after adapter normalization."""

    type: ProviderStreamEventType
    text: str | None = None
    finish_reason: str | None = None
    usage: LLMTokenUsage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def started(
        cls,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ProviderLLMStreamEvent":
        return cls(type="started", metadata=dict(metadata or {}))

    @classmethod
    def delta(
        cls,
        *,
        text: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ProviderLLMStreamEvent":
        return cls(type="delta", text=text, metadata=dict(metadata or {}))

    @classmethod
    def metadata_event(
        cls,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ProviderLLMStreamEvent":
        return cls(type="metadata", metadata=dict(metadata or {}))

    @classmethod
    def completed(
        cls,
        *,
        finish_reason: str | None = None,
        usage: LLMTokenUsage | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "ProviderLLMStreamEvent":
        return cls(
            type="completed",
            finish_reason=finish_reason,
            usage=usage,
            metadata=dict(metadata or {}),
        )