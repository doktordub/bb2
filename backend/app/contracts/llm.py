"""LLM gateway contracts and normalized request or response models."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

if TYPE_CHECKING:
    from app.contracts.context import OrchestrationContext

LLMRole = Literal["system", "user", "assistant", "tool"]
LLMContentPartType = Literal["text", "image_url", "json"]
LLMResponseFormatType = Literal["text", "json_object", "json_schema"]
LLMStreamEventType = Literal["started", "delta", "metadata", "completed", "error"]
LLMToolType = Literal["function"]
LLMToolChoiceType = Literal["auto", "none", "required", "function"]


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
class LLMToolFunction:
    """Provider-neutral tool definition function payload."""

    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None
    strict: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LLMToolFunction":
        parameters = value.get("parameters")
        metadata = value.get("metadata")
        strict_value = value.get("strict")
        return cls(
            name=cast(str, value.get("name", "")),
            description=cast(str | None, value.get("description")),
            parameters=dict(parameters) if isinstance(parameters, Mapping) else None,
            strict=strict_value if isinstance(strict_value, bool) else None,
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )


@dataclass(slots=True)
class LLMToolDefinition:
    """Provider-neutral tool definition used by native tool-calling requests."""

    function: LLMToolFunction | Mapping[str, Any]
    type: LLMToolType = "function"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.function, Mapping):
            self.function = LLMToolFunction.from_mapping(self.function)
        elif not isinstance(self.function, LLMToolFunction):
            raise TypeError("LLM tool definitions require an LLMToolFunction or mapping.")

        if not isinstance(self.metadata, dict):
            self.metadata = dict(self.metadata)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LLMToolDefinition":
        metadata = value.get("metadata")
        function = value.get("function")
        if not isinstance(function, Mapping):
            raise TypeError("LLM tool definitions require a function mapping.")
        return cls(
            function=function,
            type=cast(LLMToolType, value.get("type", "function")),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )


@dataclass(slots=True)
class LLMToolChoice:
    """Provider-neutral tool choice used by native tool-calling requests."""

    type: LLMToolChoiceType = "auto"
    function: LLMToolFunction | Mapping[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.function, Mapping):
            self.function = LLMToolFunction.from_mapping(self.function)
        elif self.function is not None and not isinstance(self.function, LLMToolFunction):
            raise TypeError("LLM tool choices require an LLMToolFunction, mapping, or None.")

        if not isinstance(self.metadata, dict):
            self.metadata = dict(self.metadata)

    @classmethod
    def from_value(
        cls,
        value: "LLMToolChoice | Mapping[str, Any] | str",
    ) -> "LLMToolChoice":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalized = value.strip() or "auto"
            return cls(type=cast(LLMToolChoiceType, normalized))
        if not isinstance(value, Mapping):
            raise TypeError("LLM tool choice values must be strings, mappings, or LLMToolChoice values.")

        metadata = value.get("metadata")
        function = value.get("function")
        return cls(
            type=cast(LLMToolChoiceType, value.get("type", "auto")),
            function=function if isinstance(function, Mapping) else None,
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )


@dataclass(slots=True)
class LLMToolCallFunction:
    """Normalized assistant tool-call function payload."""

    name: str
    arguments: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LLMToolCallFunction":
        metadata = value.get("metadata")
        arguments = value.get("arguments")
        return cls(
            name=cast(str, value.get("name", "")),
            arguments=arguments if isinstance(arguments, str) else "",
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )


@dataclass(slots=True)
class LLMToolCall:
    """Normalized assistant tool-call object."""

    function: LLMToolCallFunction | Mapping[str, Any]
    id: str | None = None
    type: LLMToolType = "function"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.function, Mapping):
            self.function = LLMToolCallFunction.from_mapping(self.function)
        elif not isinstance(self.function, LLMToolCallFunction):
            raise TypeError("LLM tool calls require an LLMToolCallFunction or mapping.")

        if not isinstance(self.metadata, dict):
            self.metadata = dict(self.metadata)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LLMToolCall":
        metadata = value.get("metadata")
        function = value.get("function")
        if not isinstance(function, Mapping):
            raise TypeError("LLM tool calls require a function mapping.")
        return cls(
            function=function,
            id=cast(str | None, value.get("id")),
            type=cast(LLMToolType, value.get("type", "function")),
            metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
        )


@dataclass(slots=True)
class LLMMessage:
    """Single logical message sent to an LLM gateway."""

    role: LLMRole
    content: str | list[LLMContentPart]
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
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

        normalized_tool_calls: list[LLMToolCall] = []
        for tool_call in self.tool_calls:
            if isinstance(tool_call, LLMToolCall):
                normalized_tool_calls.append(tool_call)
            elif isinstance(tool_call, Mapping):
                normalized_tool_calls.append(LLMToolCall.from_mapping(tool_call))
            else:
                raise TypeError("LLM message tool calls must be mappings or LLMToolCall values.")
        self.tool_calls = normalized_tool_calls

        if not isinstance(self.metadata, dict):
            self.metadata = dict(self.metadata)


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
    tools: list[LLMToolDefinition] = field(default_factory=list)
    tool_choice: LLMToolChoice | Mapping[str, Any] | str | None = None
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

        normalized_tools: list[LLMToolDefinition] = []
        for tool in self.tools:
            if isinstance(tool, LLMToolDefinition):
                normalized_tools.append(tool)
            elif isinstance(tool, Mapping):
                normalized_tools.append(LLMToolDefinition.from_mapping(tool))
            else:
                raise TypeError("LLM requests require LLMToolDefinition values or mappings for tools.")
        self.tools = normalized_tools

        if self.tool_choice is not None and not isinstance(self.tool_choice, LLMToolChoice):
            self.tool_choice = LLMToolChoice.from_value(self.tool_choice)

        if not isinstance(self.metadata, dict):
            self.metadata = dict(self.metadata)

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
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    reasoning: dict[str, Any] = field(default_factory=dict)
    usage: LLMTokenUsage | None = None
    raw_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_tool_calls: list[LLMToolCall] = []
        for tool_call in self.tool_calls:
            if isinstance(tool_call, LLMToolCall):
                normalized_tool_calls.append(tool_call)
            elif isinstance(tool_call, Mapping):
                normalized_tool_calls.append(LLMToolCall.from_mapping(tool_call))
            else:
                raise TypeError("LLM responses require LLMToolCall values or mappings.")
        self.tool_calls = normalized_tool_calls

        if not isinstance(self.reasoning, dict):
            self.reasoning = dict(self.reasoning)

        if not isinstance(self.metadata, dict):
            self.metadata = dict(self.metadata)


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
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    reasoning: dict[str, Any] = field(default_factory=dict)
    usage: LLMTokenUsage | None = None
    error: LLMErrorDetail | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_tool_calls: list[LLMToolCall] = []
        for tool_call in self.tool_calls:
            if isinstance(tool_call, LLMToolCall):
                normalized_tool_calls.append(tool_call)
            elif isinstance(tool_call, Mapping):
                normalized_tool_calls.append(LLMToolCall.from_mapping(tool_call))
            else:
                raise TypeError("LLM stream events require LLMToolCall values or mappings.")
        self.tool_calls = normalized_tool_calls

        if not isinstance(self.reasoning, dict):
            self.reasoning = dict(self.reasoning)

        if not isinstance(self.metadata, dict):
            self.metadata = dict(self.metadata)

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
        tool_calls: Sequence[LLMToolCall | Mapping[str, Any]] | None = None,
        reasoning: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "LLMStreamEvent":
        normalized_tool_calls = [
            item if isinstance(item, LLMToolCall) else LLMToolCall.from_mapping(item)
            for item in (tool_calls or ())
        ]
        return cls(
            type="delta",
            text=text,
            profile=profile,
            provider=provider,
            model=model,
            tool_calls=normalized_tool_calls,
            reasoning=dict(reasoning or {}),
            metadata=dict(metadata or {}),
        )

    @classmethod
    def completed(
        cls,
        *,
        profile: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        tool_calls: Sequence[LLMToolCall | Mapping[str, Any]] | None = None,
        finish_reason: str | None = None,
        reasoning: Mapping[str, Any] | None = None,
        usage: LLMTokenUsage | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "LLMStreamEvent":
        normalized_tool_calls = [
            item if isinstance(item, LLMToolCall) else LLMToolCall.from_mapping(item)
            for item in (tool_calls or ())
        ]
        return cls(
            type="completed",
            profile=profile,
            provider=provider,
            model=model,
            tool_calls=normalized_tool_calls,
            finish_reason=finish_reason,
            reasoning=dict(reasoning or {}),
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