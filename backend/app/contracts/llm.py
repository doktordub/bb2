"""LLM gateway contracts and normalized request or response models."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

if TYPE_CHECKING:
    from app.contracts.context import OrchestrationContext

LLMRole = Literal["system", "user", "assistant", "tool"]
LLMContentPartType = Literal["text", "image_url", "json"]
LLMResponseFormatType = Literal["text", "json_object", "json_schema"]
LLMStreamEventType = Literal["started", "delta", "metadata", "completed", "error"]


@dataclass(slots=True)
class LLMContentPart:
    """One structured content part in a logical LLM message."""

    type: LLMContentPartType
    text: str | None = None
    image_url: str | None = None
    json_value: Any | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LLMContentPart":
        return cls(
            type=cast(LLMContentPartType, value.get("type", "text")),
            text=cast(str | None, value.get("text")),
            image_url=cast(str | None, value.get("image_url")),
            json_value=value.get("json_value"),
        )


@dataclass(slots=True)
class LLMResponseFormat:
    """Provider-neutral structured-output preference."""

    type: LLMResponseFormatType = "text"
    schema_name: str | None = None
    json_schema: dict[str, Any] | None = None
    strict: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LLMResponseFormat":
        schema = value.get("json_schema")
        return cls(
            type=cast(LLMResponseFormatType, value.get("type", "text")),
            schema_name=cast(str | None, value.get("schema_name")),
            json_schema=dict(schema) if isinstance(schema, Mapping) else None,
            strict=bool(value.get("strict", False)),
        )


@dataclass(slots=True)
class LLMMessage:
    """Single logical message sent to an LLM gateway."""

    role: LLMRole
    content: str | list[LLMContentPart]
    name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.content, list):
            normalized: list[LLMContentPart] = []
            for part in self.content:
                if isinstance(part, LLMContentPart):
                    normalized.append(part)
                elif isinstance(part, Mapping):
                    normalized.append(LLMContentPart.from_mapping(part))
                else:
                    raise TypeError("LLM message content parts must be mappings or LLMContentPart values.")
            self.content = normalized


@dataclass(slots=True)
class LLMRequest:
    """Provider-neutral LLM completion request."""

    messages: list[LLMMessage]
    component: str | None = None
    profile: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    response_format: LLMResponseFormat | Mapping[str, Any] | None = None
    stream: bool = False
    timeout_seconds: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    max_tokens: int | None = None

    def __post_init__(self) -> None:
        normalized_messages: list[LLMMessage] = []
        for message in self.messages:
            if isinstance(message, LLMMessage):
                normalized_messages.append(message)
            elif isinstance(message, Mapping):
                normalized_messages.append(LLMMessage(**message))
            else:
                raise TypeError("LLM requests require LLMMessage values or mappings.")
        self.messages = normalized_messages

        if isinstance(self.response_format, Mapping):
            self.response_format = LLMResponseFormat.from_mapping(self.response_format)

        if self.max_output_tokens is None and self.max_tokens is not None:
            self.max_output_tokens = self.max_tokens
        elif self.max_tokens is None and self.max_output_tokens is not None:
            self.max_tokens = self.max_output_tokens


@dataclass(slots=True)
class LLMTokenUsage:
    """Normalized token-usage information for a gateway response."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


LLMUsage = LLMTokenUsage


@dataclass(slots=True)
class LLMErrorDetail:
    """Normalized, provider-neutral LLM error detail."""

    type: str
    code: str | None = None
    message: str | None = None
    retryable: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMResponse:
    """Normalized synchronous completion response."""

    text: str
    profile: str
    provider: str
    model: str
    finish_reason: str | None = None
    usage: LLMTokenUsage | None = None
    raw_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMProviderHealthSummary:
    """Safe provider-level health summary."""

    status: str
    type: str
    enabled: bool


@dataclass(slots=True)
class LLMProfileHealthSummary:
    """Safe profile-level health summary."""

    status: str
    provider: str
    enabled: bool
    supports_streaming: bool


@dataclass(slots=True)
class LLMProfileSummary:
    """Safe summary of one logical LLM profile."""

    name: str
    provider: str
    model: str
    enabled: bool = True
    supports_streaming: bool = True
    supports_json_schema: bool = False
    supports_tool_calling: bool = False
    fallback_profiles: tuple[str, ...] = field(default_factory=tuple)
    allowed_for: dict[str, tuple[str, ...]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMHealthResult:
    """Safe health summary for the public LLM gateway surface."""

    status: str
    providers_configured: bool
    profiles_configured: bool
    default_profile: str | None
    providers: dict[str, LLMProviderHealthSummary] = field(default_factory=dict)
    profiles: dict[str, LLMProfileHealthSummary] = field(default_factory=dict)


@dataclass(slots=True)
class LLMStreamEvent:
    """Normalized stream lifecycle event emitted by the LLM gateway."""

    type: LLMStreamEventType
    text: str | None = None
    profile: str | None = None
    provider: str | None = None
    model: str | None = None
    finish_reason: str | None = None
    usage: LLMTokenUsage | None = None
    error: LLMErrorDetail | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def started(
        cls,
        *,
        profile: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "LLMStreamEvent":
        return cls(
            type="started",
            profile=profile,
            provider=provider,
            model=model,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def delta(
        cls,
        *,
        text: str,
        profile: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "LLMStreamEvent":
        return cls(
            type="delta",
            text=text,
            profile=profile,
            provider=provider,
            model=model,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def completed(
        cls,
        *,
        profile: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        finish_reason: str | None = None,
        usage: LLMTokenUsage | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "LLMStreamEvent":
        return cls(
            type="completed",
            profile=profile,
            provider=provider,
            model=model,
            finish_reason=finish_reason,
            usage=usage,
            metadata=dict(metadata or {}),
        )


@dataclass(slots=True)
class LLMStreamDelta:
    """Compatibility wrapper for older delta-only test call sites."""

    text_delta: str
    profile: str | None = None
    provider: str | None = None
    model: str | None = None
    is_final: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_event(self) -> LLMStreamEvent:
        if self.is_final:
            return LLMStreamEvent.completed(
                profile=self.profile,
                provider=self.provider,
                model=self.model,
                metadata=self.metadata,
            )
        return LLMStreamEvent.delta(
            text=self.text_delta,
            profile=self.profile,
            provider=self.provider,
            model=self.model,
            metadata=self.metadata,
        )


class LLMGateway(Protocol):
    """Provider-neutral gateway used by agents and strategies."""

    async def complete(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> LLMResponse:
        ...

    def stream(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[LLMStreamEvent]:
        ...

    async def health(self) -> LLMHealthResult:
        ...

    async def list_profiles(self) -> list[LLMProfileSummary]:
        ...