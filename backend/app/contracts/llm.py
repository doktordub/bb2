"""LLM gateway contracts and normalized request or response models."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from app.contracts.context import OrchestrationContext

LLMRole = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class LLMMessage:
    """Single logical message sent to an LLM gateway."""

    role: LLMRole
    content: str
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMRequest:
    """Provider-neutral LLM completion request."""

    component: str
    messages: list[LLMMessage]
    profile: str | None = None
    response_format: dict[str, Any] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMUsage:
    """Normalized token-usage information for a gateway response."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMResponse:
    """Normalized synchronous completion response."""

    text: str
    profile: str
    provider: str
    model: str
    usage: LLMUsage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMStreamDelta:
    """Normalized incremental streaming update from the LLM gateway."""

    text_delta: str
    profile: str | None = None
    provider: str | None = None
    model: str | None = None
    is_final: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMGateway(Protocol):
    """Provider-neutral gateway used by agents and strategies."""

    async def complete(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> LLMResponse:
        ...

    async def stream(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[LLMStreamDelta]:
        ...