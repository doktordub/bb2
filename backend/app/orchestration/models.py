"""Orchestration-owned request, result, and summary models."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.orchestration.state_delta import WorkflowStateDelta, WorkflowStateSnapshot
    from app.visualization.models import ChartArtifact, ContextContribution

_MAX_TEXT_CHARS = 8_000
_MAX_METADATA_ITEMS = 32
_MAX_METADATA_DEPTH = 4
_SENSITIVE_KEY_PARTS = (
    "secret",
    "token",
    "password",
    "credential",
    "authorization",
    "api_key",
    "apikey",
    "cookie",
)
_UNSAFE_KEY_PARTS = (
    "traceback",
    "stack_trace",
    "stacktrace",
    "raw_prompt",
    "prompt_messages",
    "prompt_template",
    "provider_chunk",
    "raw_chunk",
    "raw_payload",
    "provider_payload",
    "provider_response",
    "provider_request",
    "tool_payload",
    "memory_record",
    "workflow_state",
    "hidden_reasoning",
    "chain_of_thought",
    "scratchpad",
)
_ALLOWED_STRATEGY_PLAN_ACTION_TYPES = frozenset(
    {"memory_search", "tool_call", "agent_invoke", "llm_call", "request_user_input", "finalize"}
)
_ALLOWED_TASK_ASSESSMENT_RESPONSE_MODES = frozenset(
    {"direct_answer", "request_user_input", "planned_execution"}
)


def sanitize_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a bounded, secret-safe metadata mapping."""

    if metadata is None:
        return {}
    return _sanitize_mapping(metadata, depth=0)


def _sanitize_mapping(metadata: Mapping[str, Any], *, depth: int) -> dict[str, Any]:
    if depth > _MAX_METADATA_DEPTH:
        return {}

    sanitized: dict[str, Any] = {}
    for raw_key, raw_value in list(metadata.items())[:_MAX_METADATA_ITEMS]:
        if not isinstance(raw_key, str):
            continue
        key = raw_key.strip()
        if not key or _is_blocked_key(key):
            continue
        sanitized[key] = _sanitize_value(raw_value, depth=depth + 1)
    return sanitized


def _sanitize_sequence(values: Sequence[object], *, depth: int) -> list[Any]:
    if depth > _MAX_METADATA_DEPTH:
        return []

    sanitized: list[Any] = []
    for item in list(values)[:_MAX_METADATA_ITEMS]:
        sanitized.append(_sanitize_value(item, depth=depth + 1))
    return sanitized


def _sanitize_value(value: Any, *, depth: int) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, Mapping):
        return _sanitize_mapping(value, depth=depth)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return _sanitize_sequence(value, depth=depth)
    return value.__class__.__name__


def _is_blocked_key(key: str) -> bool:
    lowered = key.casefold()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS + _UNSAFE_KEY_PARTS)


def _normalize_text(value: object, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise TypeError("Expected a string value.")

    normalized = value.strip()
    if not normalized and not allow_empty:
        raise ValueError("Expected a non-empty string value.")
    if len(normalized) <= _MAX_TEXT_CHARS:
        return normalized
    return normalized[: _MAX_TEXT_CHARS - 1].rstrip() + "..."


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return _normalize_text(normalized)


def _normalize_optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _normalize_bool(value: object, *, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _normalize_required_identifier(value: object, *, field_name: str) -> str:
    try:
        normalized = _normalize_text(value, allow_empty=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field_name}.") from exc
    return normalized


def _coerce_identifier_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return ()
    return _normalize_identifier_tuple(value)


def _normalize_identifier_tuple(values: Sequence[object]) -> tuple[str, ...]:
    normalized: list[str] = []
    for item in values:
        text = _normalize_optional_text(item)
        if text is not None:
            normalized.append(text)
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    """Safe conversation message projection carried across orchestration boundaries."""

    role: str
    content: str
    created_at: str | None = None
    request_id: str | None = None
    turn_id: str | None = None
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _normalize_required_identifier(self.role, field_name="role"))
        object.__setattr__(self, "content", _normalize_text(self.content))
        object.__setattr__(self, "created_at", _normalize_optional_text(self.created_at))
        object.__setattr__(self, "request_id", _normalize_optional_text(self.request_id))
        object.__setattr__(self, "turn_id", _normalize_optional_text(self.turn_id))
        object.__setattr__(self, "trace_id", _normalize_optional_text(self.trace_id))
        object.__setattr__(self, "metadata", _enrich_conversation_metadata(self))

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "ConversationMessage":
        raw_metadata_value = item.get("metadata")
        raw_metadata: Mapping[str, Any] = raw_metadata_value if isinstance(raw_metadata_value, Mapping) else {}
        return cls(
            role=_normalize_optional_text(item.get("role")) or "assistant",
            content=_normalize_optional_text(item.get("content")) or "",
            created_at=_normalize_optional_text(item.get("created_at")),
            request_id=_normalize_optional_text(item.get("request_id")) or _normalize_optional_text(raw_metadata.get("request_id")),
            turn_id=_normalize_optional_text(item.get("turn_id")) or _normalize_optional_text(raw_metadata.get("turn_id")),
            trace_id=_normalize_optional_text(item.get("trace_id")) or _normalize_optional_text(raw_metadata.get("trace_id")),
            metadata=sanitize_metadata(raw_metadata),
        )

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.created_at is not None:
            data["created_at"] = self.created_at
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data


def _enrich_conversation_metadata(message: ConversationMessage) -> dict[str, Any]:
    metadata = sanitize_metadata(message.metadata)
    if message.request_id is not None:
        metadata.setdefault("request_id", message.request_id)
    if message.turn_id is not None:
        metadata.setdefault("turn_id", message.turn_id)
    if message.trace_id is not None:
        metadata.setdefault("trace_id", message.trace_id)
    return metadata


@dataclass(frozen=True, slots=True)
class OrchestrationStepSummary:
    """Bounded description of one orchestration step."""

    step_id: str
    step_type: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    safe_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _normalize_required_identifier(self.step_id, field_name="step_id"))
        object.__setattr__(self, "step_type", _normalize_required_identifier(self.step_type, field_name="step_type"))
        object.__setattr__(self, "status", _normalize_required_identifier(self.status, field_name="status"))
        object.__setattr__(self, "started_at", _normalize_optional_text(self.started_at))
        object.__setattr__(self, "completed_at", _normalize_optional_text(self.completed_at))
        object.__setattr__(self, "duration_ms", _normalize_optional_int(self.duration_ms))
        object.__setattr__(self, "safe_message", _normalize_optional_text(self.safe_message))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "OrchestrationStepSummary":
        return cls(
            step_id=_normalize_optional_text(item.get("step_id") or item.get("id")) or "step",
            step_type=_normalize_optional_text(item.get("step_type") or item.get("type")) or "unknown",
            status=_normalize_optional_text(item.get("status")) or "completed",
            started_at=_normalize_optional_text(item.get("started_at")),
            completed_at=_normalize_optional_text(item.get("completed_at")),
            duration_ms=_normalize_optional_int(item.get("duration_ms")),
            safe_message=_normalize_optional_text(item.get("safe_message") or item.get("message")),
            metadata=sanitize_metadata(item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}),
        )

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "step_id": self.step_id,
            "step_type": self.step_type,
            "status": self.status,
        }
        if self.started_at is not None:
            data["started_at"] = self.started_at
        if self.completed_at is not None:
            data["completed_at"] = self.completed_at
        if self.duration_ms is not None:
            data["duration_ms"] = self.duration_ms
        if self.safe_message is not None:
            data["safe_message"] = self.safe_message
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class StrategyPlanStep:
    """One validated bounded-planner step."""

    step_id: str
    action_type: str
    name: str
    inputs: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "step_id", _normalize_required_identifier(self.step_id, field_name="step_id"))
        normalized_action = _normalize_required_identifier(self.action_type, field_name="action_type")
        if normalized_action not in _ALLOWED_STRATEGY_PLAN_ACTION_TYPES:
            allowed = ", ".join(sorted(_ALLOWED_STRATEGY_PLAN_ACTION_TYPES))
            raise ValueError(f"Invalid action_type '{normalized_action}'. Allowed values: {allowed}.")
        object.__setattr__(self, "action_type", normalized_action)
        object.__setattr__(self, "name", _normalize_required_identifier(self.name, field_name="name"))
        object.__setattr__(self, "inputs", sanitize_metadata(self.inputs))
        object.__setattr__(self, "depends_on", _normalize_identifier_tuple(self.depends_on))

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "StrategyPlanStep":
        return cls(
            step_id=_normalize_optional_text(item.get("step_id") or item.get("id")) or "step",
            action_type=_normalize_optional_text(item.get("action_type") or item.get("action")) or "finalize",
            name=_normalize_optional_text(item.get("name")) or "step",
            inputs=sanitize_metadata(item.get("inputs") if isinstance(item.get("inputs"), Mapping) else {}),
            depends_on=_coerce_identifier_sequence(item.get("depends_on")),
        )

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "step_id": self.step_id,
            "action_type": self.action_type,
            "name": self.name,
        }
        if self.inputs:
            data["inputs"] = dict(self.inputs)
        if self.depends_on:
            data["depends_on"] = list(self.depends_on)
        return data


@dataclass(frozen=True, slots=True)
class TaskAssessment:
    """Structured task-first assessment returned before bounded execution begins."""

    request_kind: str
    response_mode: str
    direct_answer_eligible: bool = False
    direct_answer: str | None = None
    clarification_question: str | None = None
    missing_required_inputs: tuple[str, ...] = ()
    required_deterministic_computations: tuple[str, ...] = ()
    suggested_task_list: tuple[StrategyPlanStep, ...] = ()
    preferred_agents: tuple[str, ...] = ()
    preferred_tools: tuple[str, ...] = ()
    visualization_intent: bool = False
    safe_goal: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_kind",
            _normalize_required_identifier(self.request_kind, field_name="request_kind"),
        )
        normalized_response_mode = _normalize_required_identifier(
            self.response_mode,
            field_name="response_mode",
        )
        if normalized_response_mode not in _ALLOWED_TASK_ASSESSMENT_RESPONSE_MODES:
            allowed = ", ".join(sorted(_ALLOWED_TASK_ASSESSMENT_RESPONSE_MODES))
            raise ValueError(
                f"Invalid response_mode '{normalized_response_mode}'. Allowed values: {allowed}."
            )
        object.__setattr__(self, "response_mode", normalized_response_mode)
        object.__setattr__(self, "direct_answer_eligible", bool(self.direct_answer_eligible))
        object.__setattr__(self, "direct_answer", _normalize_optional_text(self.direct_answer))
        object.__setattr__(
            self,
            "clarification_question",
            _normalize_optional_text(self.clarification_question),
        )
        object.__setattr__(
            self,
            "missing_required_inputs",
            _normalize_identifier_tuple(self.missing_required_inputs),
        )
        object.__setattr__(
            self,
            "required_deterministic_computations",
            _normalize_identifier_tuple(self.required_deterministic_computations),
        )
        object.__setattr__(self, "suggested_task_list", tuple(self.suggested_task_list))
        object.__setattr__(self, "preferred_agents", _normalize_identifier_tuple(self.preferred_agents))
        object.__setattr__(self, "preferred_tools", _normalize_identifier_tuple(self.preferred_tools))
        object.__setattr__(self, "visualization_intent", bool(self.visualization_intent))
        object.__setattr__(self, "safe_goal", _normalize_optional_text(self.safe_goal))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))

        if self.response_mode == "direct_answer":
            if self.direct_answer is None:
                raise ValueError("Task assessment direct_answer mode requires direct_answer.")
            object.__setattr__(self, "direct_answer_eligible", True)
        elif self.response_mode == "request_user_input":
            if self.clarification_question is None:
                raise ValueError(
                    "Task assessment request_user_input mode requires clarification_question."
                )
            object.__setattr__(self, "direct_answer_eligible", False)
        elif not self.suggested_task_list:
            raise ValueError(
                "Task assessment planned_execution mode requires suggested_task_list."
            )

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "TaskAssessment":
        nested = item.get("assessment") if isinstance(item.get("assessment"), Mapping) else item.get("task_assessment")
        payload = nested if isinstance(nested, Mapping) else item
        raw_task_list = payload.get("suggested_task_list")
        if raw_task_list is None:
            raw_task_list = payload.get("tasks")
        raw_task_steps = _coerce_task_assessment_step_mappings(raw_task_list)
        task_list = _normalize_task_assessment_steps(payload, raw_task_steps)
        visualization_intent = _coerce_visualization_intent(payload, raw_task_steps)
        preferred_agents = _coerce_identifier_sequence(payload.get("preferred_agents"))
        if visualization_intent and "chart_agent" not in preferred_agents:
            preferred_agents = ("chart_agent",)

        return cls(
            request_kind=_normalize_optional_text(payload.get("request_kind") or payload.get("kind")) or "general_request",
            response_mode=_normalize_optional_text(payload.get("response_mode") or payload.get("branch")) or "planned_execution",
            direct_answer_eligible=_normalize_bool(
                payload.get("direct_answer_eligible"),
                default=_normalize_optional_text(payload.get("response_mode") or payload.get("branch"))
                == "direct_answer",
            ),
            direct_answer=_normalize_optional_text(payload.get("direct_answer") or payload.get("answer")),
            clarification_question=_normalize_optional_text(
                payload.get("clarification_question") or payload.get("question")
            ),
            missing_required_inputs=_coerce_identifier_sequence(
                payload.get("missing_required_inputs") or payload.get("missing_inputs")
            ),
            required_deterministic_computations=_coerce_identifier_sequence(
                payload.get("required_deterministic_computations")
                or payload.get("deterministic_computations")
            ),
            suggested_task_list=tuple(task_list),
            preferred_agents=preferred_agents,
            preferred_tools=_coerce_identifier_sequence(payload.get("preferred_tools")),
            visualization_intent=visualization_intent,
            safe_goal=_normalize_optional_text(payload.get("safe_goal") or payload.get("goal")),
            metadata=sanitize_metadata(payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}),
        )

    @classmethod
    def from_payload(cls, payload: object) -> "TaskAssessment":
        if isinstance(payload, TaskAssessment):
            return payload
        if isinstance(payload, Mapping):
            return cls.from_mapping(payload)
        if isinstance(payload, str):
            decoded = _extract_json_mapping_payload(payload)
            if not isinstance(decoded, Mapping):
                raise TypeError("Task assessment payload must decode to a mapping.")
            return cls.from_mapping(decoded)
        raise TypeError("Unsupported task assessment payload.")

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "request_kind": self.request_kind,
            "response_mode": self.response_mode,
            "direct_answer_eligible": self.direct_answer_eligible,
            "missing_required_inputs": list(self.missing_required_inputs),
            "required_deterministic_computations": list(self.required_deterministic_computations),
            "suggested_task_list": [step.as_dict() for step in self.suggested_task_list],
            "preferred_agents": list(self.preferred_agents),
            "preferred_tools": list(self.preferred_tools),
            "visualization_intent": self.visualization_intent,
        }
        if self.direct_answer is not None:
            data["direct_answer"] = self.direct_answer
        if self.clarification_question is not None:
            data["clarification_question"] = self.clarification_question
        if self.safe_goal is not None:
            data["safe_goal"] = self.safe_goal
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data


def _extract_json_mapping_payload(text: str) -> Mapping[str, Any] | None:
    normalized = text.strip()
    if not normalized:
        return None

    decoded = _try_decode_json_mapping(normalized)
    if decoded is not None:
        return decoded

    unfenced = _strip_json_fence(normalized)
    if unfenced != normalized:
        decoded = _try_decode_json_mapping(unfenced)
        if decoded is not None:
            return decoded

    decoder = json.JSONDecoder()
    for index, character in enumerate(normalized):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(normalized[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            return payload
    return None


def _try_decode_json_mapping(text: str) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, Mapping):
        return payload
    return None


def _strip_json_fence(text: str) -> str:
    normalized = text.strip()
    if not normalized.startswith("```"):
        return normalized
    lines = normalized.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return normalized


def _coerce_task_assessment_step_mappings(value: object) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise TypeError("Task assessment suggested_task_list must be a sequence.")

    normalized: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise TypeError("Task assessment suggested_task_list entries must be mappings.")
        normalized.append(item)
    return tuple(normalized)


def _normalize_task_assessment_steps(
    payload: Mapping[str, Any],
    raw_steps: Sequence[Mapping[str, Any]],
) -> tuple[StrategyPlanStep, ...]:
    parsed_steps: list[StrategyPlanStep] = []
    try:
        for raw_step in raw_steps:
            parsed_steps.append(StrategyPlanStep.from_mapping(raw_step))
    except (TypeError, ValueError):
        if _looks_like_visualization_assessment(payload, raw_steps):
            return (_default_visualization_task_step(),)
        raise

    if parsed_steps:
        return tuple(parsed_steps)
    if _looks_like_visualization_assessment(payload, raw_steps):
        return (_default_visualization_task_step(),)
    return ()


def _coerce_visualization_intent(
    payload: Mapping[str, Any],
    raw_steps: Sequence[Mapping[str, Any]],
) -> bool:
    raw_value = payload.get("visualization_intent")
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str) and raw_value.strip():
        return True
    return _looks_like_visualization_assessment(payload, raw_steps)


def _looks_like_visualization_assessment(
    payload: Mapping[str, Any],
    raw_steps: Sequence[Mapping[str, Any]],
) -> bool:
    request_kind = (_normalize_optional_text(payload.get("request_kind") or payload.get("kind")) or "").casefold()
    if any(token in request_kind for token in ("visual", "chart", "graph", "plot")):
        return True

    for agent_name in _coerce_identifier_sequence(payload.get("preferred_agents")):
        lowered = agent_name.casefold()
        if "chart" in lowered or "visual" in lowered:
            return True

    for raw_step in raw_steps:
        action = (_normalize_optional_text(raw_step.get("action_type") or raw_step.get("action")) or "").casefold()
        name = (_normalize_optional_text(raw_step.get("name")) or "").casefold()
        if any(token in f"{action} {name}" for token in ("chart", "graph", "plot", "visual")):
            return True
        inputs = raw_step.get("inputs")
        if isinstance(inputs, Mapping):
            for key in inputs:
                lowered_key = (_normalize_optional_text(key) or "").casefold()
                if any(token in lowered_key for token in ("chart", "graph", "plot", "visual")):
                    return True

    return False


def _default_visualization_task_step() -> StrategyPlanStep:
    return StrategyPlanStep(
        step_id="chart_1",
        action_type="agent_invoke",
        name="chart_agent",
        inputs={},
    )


@dataclass(frozen=True, slots=True)
class StrategyPlan:
    """Validated bounded-planner plan model."""

    plan_id: str
    steps: tuple[StrategyPlanStep, ...]
    safe_goal: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id", _normalize_required_identifier(self.plan_id, field_name="plan_id"))
        object.__setattr__(self, "steps", tuple(self.steps))
        object.__setattr__(self, "safe_goal", _normalize_optional_text(self.safe_goal))

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "StrategyPlan":
        raw_steps = item.get("steps")
        if not isinstance(raw_steps, Sequence) or isinstance(raw_steps, str | bytes | bytearray):
            raise TypeError("Strategy plan steps must be a sequence.")

        normalized_steps: list[StrategyPlanStep] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, Mapping):
                raise TypeError("Strategy plan steps must be mappings.")
            normalized_steps.append(StrategyPlanStep.from_mapping(raw_step))

        return cls(
            plan_id=_normalize_optional_text(item.get("plan_id") or item.get("id")) or "plan",
            steps=tuple(normalized_steps),
            safe_goal=_normalize_optional_text(item.get("safe_goal") or item.get("goal")),
        )

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "plan_id": self.plan_id,
            "steps": [step.as_dict() for step in self.steps],
        }
        if self.safe_goal is not None:
            data["safe_goal"] = self.safe_goal
        return data

    @property
    def action_types(self) -> tuple[str, ...]:
        return tuple(step.action_type for step in self.steps)


@dataclass(frozen=True, slots=True)
class ToolCallSummary:
    """Safe summary of one tool interaction."""

    tool_name: str
    status: str
    safe_message: str | None = None
    duration_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_name", _normalize_required_identifier(self.tool_name, field_name="tool_name"))
        object.__setattr__(self, "status", _normalize_required_identifier(self.status, field_name="status"))
        object.__setattr__(self, "safe_message", _normalize_optional_text(self.safe_message))
        object.__setattr__(self, "duration_ms", _normalize_optional_int(self.duration_ms))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "ToolCallSummary":
        metadata = item.get("metadata")
        return cls(
            tool_name=_normalize_optional_text(item.get("tool_name") or item.get("name") or item.get("tool")) or "tool",
            status=_normalize_optional_text(item.get("status")) or "completed",
            safe_message=_normalize_optional_text(
                item.get("safe_message") or item.get("summary") or item.get("message")
            ),
            duration_ms=_normalize_optional_int(item.get("duration_ms")),
            metadata=sanitize_metadata(metadata if isinstance(metadata, Mapping) else {}),
        )

    def as_legacy_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"tool_name": self.tool_name, "status": self.status}
        if self.safe_message is not None:
            data["safe_message"] = self.safe_message
        if self.duration_ms is not None:
            data["duration_ms"] = self.duration_ms
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class MemorySearchSummary:
    """Safe summary of one memory lookup."""

    source: str | None = None
    result_count: int = 0
    duration_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _normalize_optional_text(self.source))
        object.__setattr__(self, "result_count", max(self.result_count, 0))
        object.__setattr__(self, "duration_ms", _normalize_optional_int(self.duration_ms))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "MemorySearchSummary":
        count = item.get("result_count")
        if not isinstance(count, int) or isinstance(count, bool):
            count = item.get("count")
        return cls(
            source=_normalize_optional_text(item.get("source") or item.get("scope")),
            result_count=count if isinstance(count, int) and not isinstance(count, bool) else 0,
            duration_ms=_normalize_optional_int(item.get("duration_ms")),
            metadata=sanitize_metadata(item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}),
        )

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"result_count": self.result_count}
        if self.source is not None:
            data["source"] = self.source
        if self.duration_ms is not None:
            data["duration_ms"] = self.duration_ms
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class MemoryUpdateSummary:
    """Safe summary of one memory mutation."""

    operation: str
    status: str
    safe_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _normalize_required_identifier(self.operation, field_name="operation"))
        object.__setattr__(self, "status", _normalize_required_identifier(self.status, field_name="status"))
        object.__setattr__(self, "safe_message", _normalize_optional_text(self.safe_message))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "MemoryUpdateSummary":
        return cls(
            operation=_normalize_optional_text(item.get("operation") or item.get("type") or item.get("action")) or "memory_update",
            status=_normalize_optional_text(item.get("status")) or "completed",
            safe_message=_normalize_optional_text(
                item.get("safe_message") or item.get("summary") or item.get("message")
            ),
            metadata=sanitize_metadata(item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}),
        )

    def as_legacy_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"operation": self.operation, "status": self.status}
        if self.safe_message is not None:
            data["safe_message"] = self.safe_message
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class CitationSummary:
    """Safe citation summary attached to an orchestration result."""

    label: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _normalize_optional_text(self.label))
        object.__setattr__(self, "source", _normalize_optional_text(self.source))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "CitationSummary":
        return cls(
            label=_normalize_optional_text(item.get("label") or item.get("title")),
            source=_normalize_optional_text(item.get("source") or item.get("url") or item.get("id")),
            metadata=sanitize_metadata(item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}),
        )

    def as_legacy_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.label is not None:
            data["label"] = self.label
        if self.source is not None:
            data["source"] = self.source
        if self.metadata:
            data["metadata"] = dict(self.metadata)
        return data


@dataclass(frozen=True, slots=True)
class OrchestrationRequest:
    """Request DTO owned by the orchestration layer."""

    session_id: str
    trace_id: str
    user_id: str
    message: str
    usecase: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    workflow_state: "WorkflowStateSnapshot | None" = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _normalize_required_identifier(self.session_id, field_name="session_id"))
        object.__setattr__(self, "trace_id", _normalize_required_identifier(self.trace_id, field_name="trace_id"))
        object.__setattr__(self, "user_id", _normalize_required_identifier(self.user_id, field_name="user_id"))
        object.__setattr__(self, "message", _normalize_text(self.message))
        object.__setattr__(self, "usecase", _normalize_optional_text(self.usecase))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OrchestrationRuntimeContext:
    """Safe runtime context supplied to orchestration."""

    request_id: str
    trace_id: str
    session_id: str
    user_id: str
    project_id: str | None = None
    tenant_id: str | None = None
    timezone: str | None = None
    client: str | None = None
    cancellation_token: object | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _normalize_required_identifier(self.request_id, field_name="request_id"))
        object.__setattr__(self, "trace_id", _normalize_required_identifier(self.trace_id, field_name="trace_id"))
        object.__setattr__(self, "session_id", _normalize_required_identifier(self.session_id, field_name="session_id"))
        object.__setattr__(self, "user_id", _normalize_required_identifier(self.user_id, field_name="user_id"))
        object.__setattr__(self, "project_id", _normalize_optional_text(self.project_id))
        object.__setattr__(self, "tenant_id", _normalize_optional_text(self.tenant_id))
        object.__setattr__(self, "timezone", _normalize_optional_text(self.timezone))
        object.__setattr__(self, "client", _normalize_optional_text(self.client))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """Normalized, safe orchestration result owned by the runtime."""

    answer: str
    session_id: str
    trace_id: str
    usecase: str
    strategy_name: str
    agent_name: str | None = None
    llm_profile: str | None = None
    steps: list[OrchestrationStepSummary] = field(default_factory=list)
    tool_calls: list[ToolCallSummary] = field(default_factory=list)
    memory_searches: list[MemorySearchSummary] = field(default_factory=list)
    memory_updates: list[MemoryUpdateSummary] = field(default_factory=list)
    citations: list[CitationSummary] = field(default_factory=list)
    artifacts: list["ChartArtifact"] = field(default_factory=list)
    context_contributions: list["ContextContribution"] = field(default_factory=list)
    state_delta: "WorkflowStateDelta | None" = None
    finish_reason: str = "stop"
    duration_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "answer", _normalize_text(self.answer))
        object.__setattr__(self, "session_id", _normalize_required_identifier(self.session_id, field_name="session_id"))
        object.__setattr__(self, "trace_id", _normalize_required_identifier(self.trace_id, field_name="trace_id"))
        object.__setattr__(self, "usecase", _normalize_required_identifier(self.usecase, field_name="usecase"))
        object.__setattr__(self, "strategy_name", _normalize_required_identifier(self.strategy_name, field_name="strategy_name"))
        object.__setattr__(self, "agent_name", _normalize_optional_text(self.agent_name))
        object.__setattr__(self, "llm_profile", _normalize_optional_text(self.llm_profile))
        object.__setattr__(self, "steps", list(self.steps))
        object.__setattr__(self, "tool_calls", list(self.tool_calls))
        object.__setattr__(self, "memory_searches", list(self.memory_searches))
        object.__setattr__(self, "memory_updates", list(self.memory_updates))
        object.__setattr__(self, "citations", list(self.citations))
        object.__setattr__(self, "artifacts", list(self.artifacts))
        object.__setattr__(self, "context_contributions", list(self.context_contributions))
        object.__setattr__(self, "finish_reason", _normalize_required_identifier(self.finish_reason, field_name="finish_reason"))
        object.__setattr__(self, "duration_ms", _normalize_optional_int(self.duration_ms))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))