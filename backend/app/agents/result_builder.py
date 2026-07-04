"""Helpers for bridging structured agent results with the legacy contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.agents.models import (
    AgentOutputFormat,
    AgentOutputItem,
    PromptContextItem,
    AgentReviewResult,
    AgentRunRequest,
    AgentRunResult,
    AgentTask,
    ToolContextItem,
    AgentUsageSummary,
    AgentWarning,
)
from app.contracts.context import OrchestrationContext
from app.contracts.results import AgentResult
from app.memory.redaction import truncate_text
from app.orchestration.conversation_context import build_conversation_context_window
from app.orchestration.models import ConversationMessage
from app.orchestration.memory_intents import MemoryCandidate
from app.orchestration.models import sanitize_metadata
from app.orchestration.prompt_inputs import PromptSection
from app.orchestration.tool_intents import ToolIntent


def build_run_request_from_context(
    context: OrchestrationContext,
    *,
    agent_name: str | None = None,
    llm_profile: str | None = None,
    strategy_name: str | None = None,
    conversation_history: Sequence[ConversationMessage] | None = None,
    context_items: Sequence[PromptContextItem] = (),
    tool_context: Sequence[ToolContextItem] = (),
    available_tools: Sequence[str] = (),
    task: AgentTask | None = None,
    constraints: Sequence[str] = (),
    output_format: AgentOutputFormat | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AgentRunRequest:
    """Build a bounded structured request from the orchestration context."""

    runtime = context.runtime
    resolved_session_summary = _optional_text(context.metadata.get("session_summary"))
    if conversation_history is None:
        history_window = build_conversation_context_window(context)
        resolved_conversation_history = history_window.messages
        resolved_session_summary = history_window.session_summary or resolved_session_summary
        history_metadata = {
            "conversation_history_enabled": history_window.enabled,
            "conversation_history_turn_count": len(history_window.messages),
            "conversation_history_truncated": history_window.truncated,
            "current_turn_deduped": history_window.current_turn_deduped,
            "session_summary_used": history_window.session_summary_used,
        }
    else:
        resolved_conversation_history = tuple(conversation_history)
        history_metadata = {
            "conversation_history_enabled": bool(resolved_conversation_history),
            "conversation_history_turn_count": len(resolved_conversation_history),
            "session_summary_used": resolved_session_summary is not None,
        }

    request_metadata = dict(metadata or {})
    for key, value in history_metadata.items():
        request_metadata.setdefault(key, value)

    return AgentRunRequest(
        trace_id=context.request.trace_id or ("trace_unavailable" if runtime is None else runtime.trace_id),
        session_id=context.request.session_id,
        user_id=context.request.user_id,
        project_id=None if runtime is None else runtime.project_id,
        usecase=context.request.usecase or "default",
        message=context.request.message,
        llm_profile=llm_profile or _resolve_llm_profile(context, agent_name=agent_name),
        strategy_name=(
            strategy_name
            or _optional_text(context.runtime_metadata.get("strategy_name"))
            or _optional_text(context.runtime_metadata.get("strategy"))
        ),
        session_summary=resolved_session_summary,
        conversation_history=resolved_conversation_history,
        context_items=tuple(context_items),
        tool_context=tuple(tool_context),
        available_tools=tuple(available_tools) or _resolve_available_tools(context, agent_name=agent_name),
        task=task,
        constraints=tuple(item for item in constraints if _optional_text(item) is not None),
        output_format=output_format,
        metadata=sanitize_metadata(request_metadata),
    )


def build_run_result(
    *,
    status: str = "completed",
    answer: str | None = None,
    agent_name: str | None = None,
    llm_profile: str | None = None,
    tool_intents: Sequence[ToolIntent] = (),
    memory_candidates: Sequence[MemoryCandidate] = (),
    review: AgentReviewResult | None = None,
    usage: AgentUsageSummary | None = None,
    output_items: Sequence[AgentOutputItem] = (),
    warnings: Sequence[AgentWarning] = (),
    metadata: Mapping[str, Any] | None = None,
) -> AgentRunResult:
    """Build a structured result with consistent defaults."""

    return AgentRunResult(
        status=status,
        answer=answer,
        agent_name=agent_name,
        llm_profile=llm_profile,
        tool_intents=tuple(tool_intents),
        memory_candidates=tuple(memory_candidates),
        review=review,
        usage=usage,
        output_items=tuple(output_items),
        warnings=tuple(warnings),
        metadata=sanitize_metadata(metadata),
    )


def build_usage_summary(
    *,
    llm_calls: int = 0,
    memory_searches: int = 0,
    memory_writes: int = 0,
    tool_calls: int = 0,
    input_chars: int | None = None,
    output_chars: int | None = None,
) -> AgentUsageSummary:
    """Build a normalized usage summary for one structured agent result."""

    return AgentUsageSummary(
        llm_calls=llm_calls,
        memory_searches=memory_searches,
        memory_writes=memory_writes,
        tool_calls=tool_calls,
        input_chars=input_chars,
        output_chars=output_chars,
    )


def build_context_output_items(
    sections: Sequence[PromptSection],
    *,
    include_labels: bool,
    max_items: int | None = None,
    max_text_chars: int = 240,
) -> tuple[AgentOutputItem, ...]:
    """Convert bounded prompt-context sections into safe citation-style output items."""

    if not include_labels:
        return ()

    items: list[AgentOutputItem] = []
    limit = len(sections) if max_items is None else max(0, max_items)
    for section in sections[:limit]:
        source_label = _source_label_from_section(section)
        if source_label is None:
            continue
        text = truncate_text(section.body, max_chars=max_text_chars)
        items.append(
            AgentOutputItem(
                type="citation",
                text=text,
                source_label=source_label,
                metadata={"section_title": section.title},
            )
        )
    return tuple(items)


def to_legacy_agent_result(
    result: AgentRunResult,
    *,
    fallback_agent_name: str | None = None,
) -> AgentResult:
    """Adapt a structured result back into the existing orchestration-facing model."""

    metadata = dict(result.metadata)
    if result.review is not None:
        metadata["review"] = {
            "status": result.review.status,
            "passed": result.review.passed,
            "score": result.review.score,
            "findings": list(result.review.findings),
            "suggested_revision": result.review.suggested_revision,
            "metadata": dict(result.review.metadata),
        }
    if result.usage is not None:
        metadata["usage"] = {
            "llm_calls": result.usage.llm_calls,
            "memory_searches": result.usage.memory_searches,
            "memory_writes": result.usage.memory_writes,
            "tool_calls": result.usage.tool_calls,
            "input_chars": result.usage.input_chars,
            "output_chars": result.usage.output_chars,
        }
    if result.warnings:
        metadata["warnings"] = [
            {
                "code": warning.code,
                "message": warning.message,
                "metadata": dict(warning.metadata),
            }
            for warning in result.warnings
        ]
    if result.output_items:
        metadata["output_items"] = [
            {
                "type": item.type,
                "text": item.text,
                "data": None if item.data is None else dict(item.data),
                "source_label": item.source_label,
                "confidence": item.confidence,
                "metadata": dict(item.metadata),
            }
            for item in result.output_items
        ]

    answer = result.answer
    if answer is None:
        answer = _first_text_output(result.output_items) or _compatibility_answer(result)

    return AgentResult(
        answer=answer,
        agent_name=result.agent_name or fallback_agent_name or "agent",
        llm_profile=result.llm_profile,
        tool_calls=[_tool_intent_to_mapping(item) for item in result.tool_intents],
        memory_updates=[_memory_candidate_to_mapping(item) for item in result.memory_candidates],
        citations=[_output_item_to_citation(item) for item in result.output_items if item.source_label],
        metadata=metadata,
    )


def from_legacy_agent_result(result: AgentResult) -> AgentRunResult:
    """Adapt the legacy result shape into the structured model when needed."""

    tool_intents: list[ToolIntent] = []
    for item in result.tool_calls:
        if not isinstance(item, Mapping):
            continue
        tool_name = _optional_text(item.get("tool_name"))
        if tool_name is None:
            continue
        arguments = item.get("arguments")
        query = _optional_text(item.get("query"))
        if query is None and isinstance(arguments, Mapping):
            query = _optional_text(arguments.get("query")) or _optional_text(arguments.get("text"))
        metadata = {
            key: value
            for key, value in item.items()
            if key not in {"tool_name", "arguments", "query"}
        }
        tool_intents.append(
            ToolIntent(
                tool_name=tool_name,
                arguments=dict(arguments) if isinstance(arguments, Mapping) else {},
                query=query or tool_name,
                metadata=metadata,
            )
        )

    memory_candidates: list[MemoryCandidate] = []
    for item in result.memory_updates:
        if isinstance(item, Mapping):
            try:
                memory_candidates.append(MemoryCandidate.from_mapping(dict(item)))
            except (TypeError, ValueError):
                continue

    return AgentRunResult(
        status="completed",
        answer=result.answer,
        agent_name=result.agent_name,
        llm_profile=result.llm_profile,
        tool_intents=tuple(tool_intents),
        memory_candidates=tuple(memory_candidates),
        metadata=sanitize_metadata(result.metadata),
    )


def _resolve_llm_profile(
    context: OrchestrationContext,
    *,
    agent_name: str | None,
) -> str | None:
    runtime_profile = _optional_text(context.runtime_metadata.get("llm_profile"))
    if runtime_profile is not None:
        return runtime_profile

    if agent_name is not None:
        profile = _optional_text(context.config.get(f"agents.plugins.{agent_name}.llm_profile"))
        if profile is not None:
            return profile
        legacy = _optional_text(context.config.get(f"agents.{agent_name}.llm_profile"))
        if legacy is not None:
            return legacy
    return None


def _resolve_available_tools(
    context: OrchestrationContext,
    *,
    agent_name: str | None,
) -> tuple[str, ...]:
    if agent_name is not None:
        configured = _read_string_list(
            context.config.get(f"agents.plugins.{agent_name}.allowed_tool_intents")
        )
        if configured:
            return tuple(configured)
        legacy = _read_string_list(context.config.get(f"agents.{agent_name}.allowed_tools"))
        if legacy:
            return tuple(legacy)

    usecase = context.request.usecase
    if usecase is None:
        return ()

    configured = _read_string_list(
        context.config.get(f"orchestration.usecases.{usecase}.tools.allowed_tools")
    )
    if configured:
        return tuple(configured)

    return tuple(_read_string_list(context.config.get(f"usecases.{usecase}.tools.allowed_tools")))


def _tool_intent_to_mapping(intent: ToolIntent) -> dict[str, Any]:
    item: dict[str, Any] = {
        "tool_name": intent.tool_name,
        "arguments": dict(intent.arguments),
        "query": intent.query,
    }
    status = _optional_text(intent.metadata.get("status"))
    if status is not None:
        item["status"] = status
    safe_message = _optional_text(intent.metadata.get("safe_message"))
    if safe_message is not None:
        item["safe_message"] = safe_message
    metadata = {
        key: value
        for key, value in intent.metadata.items()
        if key not in {"status", "safe_message"}
    }
    if metadata:
        item["metadata"] = sanitize_metadata(metadata)
    return item


def _memory_candidate_to_mapping(candidate: MemoryCandidate) -> dict[str, Any]:
    item: dict[str, Any] = {
        "text": candidate.text,
        "memory_type": candidate.memory_type,
        "scope": candidate.scope,
        "tags": list(candidate.tags),
    }
    if candidate.importance is not None:
        item["importance"] = candidate.importance
    if candidate.confidence is not None:
        item["confidence"] = candidate.confidence
    if candidate.reason is not None:
        item["reason"] = candidate.reason
    if candidate.metadata:
        item["metadata"] = dict(candidate.metadata)
    return item


def _output_item_to_citation(item: AgentOutputItem) -> dict[str, Any]:
    citation: dict[str, Any] = {
        "type": item.type,
        "source_label": item.source_label,
    }
    if item.text is not None:
        citation["text"] = item.text
    if item.confidence is not None:
        citation["confidence"] = item.confidence
    if item.metadata:
        citation["metadata"] = dict(item.metadata)
    return citation


def _compatibility_answer(result: AgentRunResult) -> str:
    if result.review is not None:
        return "Review completed." if result.review.passed else "Review completed with findings."
    if result.memory_candidates:
        count = len(result.memory_candidates)
        suffix = "candidate" if count == 1 else "candidates"
        return f"Extracted {count} memory {suffix}."
    if result.tool_intents:
        count = len(result.tool_intents)
        suffix = "intent" if count == 1 else "intents"
        return f"Prepared {count} tool {suffix}."
    return "Agent task completed."


def _first_text_output(items: Sequence[AgentOutputItem]) -> str | None:
    for item in items:
        if item.text is not None:
            return item.text
    return None


def _source_label_from_section(section: PromptSection) -> str | None:
    for key in ("source_label", "label", "source", "source_id", "document_id"):
        label = _optional_text(section.metadata.get(key))
        if label is not None:
            return label
    if section.title.casefold() == "retrieved context":
        return None
    return _optional_text(section.title)


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    normalized: list[str] = []
    for item in value:
        text = _optional_text(item)
        if text is not None:
            normalized.append(text)
    return normalized


__all__ = [
    "build_context_output_items",
    "build_run_request_from_context",
    "build_run_result",
    "build_usage_summary",
    "from_legacy_agent_result",
    "to_legacy_agent_result",
]