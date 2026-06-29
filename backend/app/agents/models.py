"""Structured agent-layer models used during the Phase 2 migration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from app.orchestration.memory_intents import MemoryCandidate
from app.orchestration.models import sanitize_metadata
from app.orchestration.prompt_inputs import PromptSection
from app.orchestration.tool_intents import ToolIntent

if TYPE_CHECKING:
    from app.agents.errors import AgentErrorDetail

AgentType = Literal[
    "general_assistant",
    "document_qa",
    "tool_using",
    "project_agent",
    "memory_curator",
    "reviewer",
    "custom",
]

AgentStreamEventType = Literal[
    "agent.started",
    "agent.prompt_built",
    "agent.llm.started",
    "agent.llm.delta",
    "agent.llm.completed",
    "agent.tool_intent.created",
    "agent.memory_candidate.created",
    "agent.review.completed",
    "agent.completed",
    "agent.failed",
    "agent.cancelled",
]

PromptContextItem = PromptSection
ToolContextItem = PromptSection


@dataclass(frozen=True, slots=True)
class AgentCapabilities:
    """Safe capability flags exposed by one configured agent."""

    answer: bool = True
    review: bool = False
    stream: bool = True
    memory_read: bool = False
    memory_write: bool = False
    memory_candidate_extract: bool = False
    tool_intents: bool = False
    tool_execute: bool = False
    self_managed_memory: bool = False
    self_managed_tools: bool = False


@dataclass(frozen=True, slots=True)
class AgentTask:
    """Safe task directive supplied by a strategy."""

    type: str
    instruction: str
    expected_outputs: tuple[str, ...] = ()
    safe_goal: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", _require_text(self.type, field_name="type"))
        object.__setattr__(
            self,
            "instruction",
            _require_text(self.instruction, field_name="instruction"),
        )
        object.__setattr__(self, "expected_outputs", _normalize_text_tuple(self.expected_outputs))
        object.__setattr__(self, "safe_goal", _optional_text(self.safe_goal))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class AgentOutputFormat:
    """Safe output-shaping hint passed to an agent."""

    kind: str = "answer"
    schema_name: str | None = None
    require_json: bool = False
    max_items: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _require_text(self.kind, field_name="kind"))
        object.__setattr__(self, "schema_name", _optional_text(self.schema_name))
        object.__setattr__(
            self,
            "max_items",
            _optional_positive_int(self.max_items, field_name="max_items"),
        )


@dataclass(frozen=True, slots=True)
class AgentWarning:
    """Safe warning emitted by the agent layer."""

    code: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _require_text(self.code, field_name="code"))
        object.__setattr__(self, "message", _require_text(self.message, field_name="message"))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class AgentReviewResult:
    """Safe review findings for reviewer-style agents."""

    status: str
    passed: bool
    score: float | None = None
    findings: tuple[str, ...] = ()
    suggested_revision: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _require_text(self.status, field_name="status"))
        object.__setattr__(self, "score", _optional_score(self.score))
        object.__setattr__(self, "findings", _normalize_text_tuple(self.findings))
        object.__setattr__(self, "suggested_revision", _optional_text(self.suggested_revision))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class AgentOutputItem:
    """Safe structured output block returned by an agent."""

    type: str
    text: str | None = None
    data: dict[str, Any] | None = None
    source_label: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", _require_text(self.type, field_name="type"))
        object.__setattr__(self, "text", _optional_text(self.text))
        object.__setattr__(self, "data", None if self.data is None else sanitize_metadata(self.data))
        object.__setattr__(self, "source_label", _optional_text(self.source_label))
        object.__setattr__(self, "confidence", _optional_score(self.confidence))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class AgentUsageSummary:
    """Safe usage counters returned by an agent."""

    llm_calls: int = 0
    memory_searches: int = 0
    memory_writes: int = 0
    tool_calls: int = 0
    input_chars: int | None = None
    output_chars: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "llm_calls", _non_negative_int(self.llm_calls, field_name="llm_calls"))
        object.__setattr__(
            self,
            "memory_searches",
            _non_negative_int(self.memory_searches, field_name="memory_searches"),
        )
        object.__setattr__(
            self,
            "memory_writes",
            _non_negative_int(self.memory_writes, field_name="memory_writes"),
        )
        object.__setattr__(self, "tool_calls", _non_negative_int(self.tool_calls, field_name="tool_calls"))
        object.__setattr__(
            self,
            "input_chars",
            _optional_non_negative_int(self.input_chars, field_name="input_chars"),
        )
        object.__setattr__(
            self,
            "output_chars",
            _optional_non_negative_int(self.output_chars, field_name="output_chars"),
        )


@dataclass(frozen=True, slots=True)
class AgentRunRequest:
    """Bounded, safe request passed into the structured agent contract."""

    trace_id: str
    session_id: str
    user_id: str | None
    project_id: str | None
    usecase: str
    message: str
    llm_profile: str | None = None
    strategy_name: str | None = None
    session_summary: str | None = None
    context_items: tuple[PromptContextItem, ...] = ()
    tool_context: tuple[ToolContextItem, ...] = ()
    available_tools: tuple[str, ...] = ()
    task: AgentTask | None = None
    constraints: tuple[str, ...] = ()
    output_format: AgentOutputFormat | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _require_text(self.trace_id, field_name="trace_id"))
        object.__setattr__(self, "session_id", _require_text(self.session_id, field_name="session_id"))
        object.__setattr__(self, "user_id", _optional_text(self.user_id))
        object.__setattr__(self, "project_id", _optional_text(self.project_id))
        object.__setattr__(self, "usecase", _require_text(self.usecase, field_name="usecase"))
        object.__setattr__(self, "message", _require_text(self.message, field_name="message"))
        object.__setattr__(self, "llm_profile", _optional_text(self.llm_profile))
        object.__setattr__(self, "strategy_name", _optional_text(self.strategy_name))
        object.__setattr__(self, "session_summary", _optional_text(self.session_summary))
        object.__setattr__(self, "available_tools", _normalize_tool_names(self.available_tools))
        object.__setattr__(self, "constraints", _normalize_text_tuple(self.constraints))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """Normalized structured result returned by one agent."""

    status: str
    answer: str | None = None
    agent_name: str | None = None
    llm_profile: str | None = None
    tool_intents: tuple[ToolIntent, ...] = ()
    memory_candidates: tuple[MemoryCandidate, ...] = ()
    review: AgentReviewResult | None = None
    usage: AgentUsageSummary | None = None
    output_items: tuple[AgentOutputItem, ...] = ()
    warnings: tuple[AgentWarning, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _require_text(self.status, field_name="status"))
        object.__setattr__(self, "answer", _optional_text(self.answer))
        object.__setattr__(self, "agent_name", _optional_text(self.agent_name))
        object.__setattr__(self, "llm_profile", _optional_text(self.llm_profile))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class AgentDescriptor:
    """Safe static descriptor published by an agent."""

    name: str
    type: AgentType | str
    display_name: str
    description: str
    enabled: bool
    llm_profile: str | None
    capabilities: AgentCapabilities
    supported_usecases: tuple[str, ...] = ()
    supported_strategies: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_text(self.name, field_name="name"))
        object.__setattr__(self, "type", _require_text(str(self.type), field_name="type"))
        object.__setattr__(
            self,
            "display_name",
            _require_text(self.display_name, field_name="display_name"),
        )
        object.__setattr__(
            self,
            "description",
            _require_text(self.description, field_name="description"),
        )
        object.__setattr__(self, "llm_profile", _optional_text(self.llm_profile))
        object.__setattr__(self, "supported_usecases", _normalize_text_tuple(self.supported_usecases))
        object.__setattr__(
            self,
            "supported_strategies",
            _normalize_text_tuple(self.supported_strategies),
        )
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class AgentHealthResult:
    """Safe readiness summary returned by one agent."""

    agent_name: str
    agent_type: str
    status: str
    enabled: bool
    configured_llm_profile: str | None = None
    prompt_profile: str | None = None
    memory_required: bool = False
    tools_required: bool = False
    streaming_supported: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "agent_name", _require_text(self.agent_name, field_name="agent_name"))
        object.__setattr__(self, "agent_type", _require_text(self.agent_type, field_name="agent_type"))
        object.__setattr__(self, "status", _require_text(self.status, field_name="status"))
        object.__setattr__(self, "configured_llm_profile", _optional_text(self.configured_llm_profile))
        object.__setattr__(self, "prompt_profile", _optional_text(self.prompt_profile))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class AgentStreamEvent:
    """Normalized safe event emitted by structured agents while streaming."""

    type: AgentStreamEventType | str
    agent_name: str
    text: str | None = None
    result: AgentRunResult | None = None
    tool_intent: ToolIntent | None = None
    memory_candidate: MemoryCandidate | None = None
    warning: AgentWarning | None = None
    error: AgentErrorDetail | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", _require_text(str(self.type), field_name="type"))
        object.__setattr__(self, "agent_name", _require_text(self.agent_name, field_name="agent_name"))
        object.__setattr__(self, "text", _optional_stream_text(self.text))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))

    @classmethod
    def started(
        cls,
        *,
        agent_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> "AgentStreamEvent":
        return cls(
            type="agent.started",
            agent_name=agent_name,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def completed(
        cls,
        *,
        agent_name: str,
        result: AgentRunResult,
        metadata: dict[str, Any] | None = None,
    ) -> "AgentStreamEvent":
        return cls(
            type="agent.completed",
            agent_name=agent_name,
            result=result,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def failed(
        cls,
        *,
        agent_name: str,
        error: AgentErrorDetail,
        metadata: dict[str, Any] | None = None,
    ) -> "AgentStreamEvent":
        return cls(
            type="agent.failed",
            agent_name=agent_name,
            error=error,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def cancelled(
        cls,
        *,
        agent_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> "AgentStreamEvent":
        return cls(
            type="agent.cancelled",
            agent_name=agent_name,
            metadata=dict(metadata or {}),
        )


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"Invalid {field_name}.")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"Invalid {field_name}.")
    return normalized if len(normalized) <= 8_000 else normalized[:7_999].rstrip() + "..."


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return _require_text(normalized, field_name="text")


def _optional_stream_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if value == "":
        return None
    return value if len(value) <= 8_000 else value[:7_999] + "..."


def _normalize_text_tuple(values: tuple[object, ...] | list[object]) -> tuple[str, ...]:
    normalized: list[str] = []
    for item in values:
        text = _optional_text(item)
        if text is not None:
            normalized.append(text)
    return tuple(normalized)


def _normalize_tool_names(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for item in values:
        tool_name = _require_text(item, field_name="available_tools")
        lowered = tool_name.casefold()
        if lowered.startswith("mcp:") or lowered.startswith("mcp/"):
            raise ValueError("Raw MCP tool names are not allowed in agent requests.")
        if " " in tool_name:
            raise ValueError("Tool names must not contain spaces.")
        normalized.append(tool_name)
    return tuple(normalized)


def _non_negative_int(value: object, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"Invalid {field_name}.")
    if value < 0:
        raise ValueError(f"Invalid {field_name}.")
    return value


def _optional_non_negative_int(value: object, *, field_name: str) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value, field_name=field_name)


def _optional_positive_int(value: object, *, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"Invalid {field_name}.")
    if value <= 0:
        raise ValueError(f"Invalid {field_name}.")
    return value


def _optional_score(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise TypeError("Invalid score.")
    normalized = float(value)
    if normalized < 0 or normalized > 1:
        raise ValueError("Invalid score.")
    return normalized


__all__ = [
    "AgentCapabilities",
    "AgentDescriptor",
    "AgentHealthResult",
    "AgentOutputFormat",
    "AgentOutputItem",
    "AgentReviewResult",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentStreamEvent",
    "AgentStreamEventType",
    "AgentTask",
    "AgentType",
    "AgentUsageSummary",
    "AgentWarning",
    "PromptContextItem",
    "ToolContextItem",
]