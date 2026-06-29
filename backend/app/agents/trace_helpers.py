"""Safe trace-summary helpers for structured agent execution."""

from __future__ import annotations

from typing import Any

from app.agents.errors import normalize_agent_error
from app.agents.models import AgentDescriptor, AgentHealthResult, AgentReviewResult, AgentRunRequest, AgentRunResult, AgentWarning
from app.orchestration.memory_intents import MemoryCandidate
from app.orchestration.models import sanitize_metadata


def build_request_trace_summary(
    request: AgentRunRequest,
    *,
    agent_name: str,
) -> dict[str, Any]:
    """Return a safe summary of one structured agent request."""

    return sanitize_metadata(
        {
            "agent_name": agent_name,
            "usecase": request.usecase,
            "strategy_name": request.strategy_name,
            "project_id_present": request.project_id is not None,
            "context_item_count": len(request.context_items),
            "tool_context_count": len(request.tool_context),
            "available_tool_count": len(request.available_tools),
            "has_task": request.task is not None,
            "constraint_count": len(request.constraints),
            "llm_profile": request.llm_profile,
        }
    )


def build_result_trace_summary(result: AgentRunResult) -> dict[str, Any]:
    """Return a safe summary of one structured agent result."""

    return sanitize_metadata(
        {
            "status": result.status,
            "agent_name": result.agent_name,
            "llm_profile": result.llm_profile,
            "answer_chars": 0 if result.answer is None else len(result.answer),
            "tool_intent_count": len(result.tool_intents),
            "memory_candidate_count": len(result.memory_candidates),
            "warning_count": len(result.warnings),
            "output_item_count": len(result.output_items),
            "has_review": result.review is not None,
        }
    )


def build_prompt_trace_summary(
    request: AgentRunRequest,
    *,
    agent_name: str,
    prompt_profile: str | None,
    message_count: int,
) -> dict[str, Any]:
    """Return a safe prompt-construction summary without prompt text."""

    return sanitize_metadata(
        {
            **build_request_trace_summary(request, agent_name=agent_name),
            "prompt_profile": prompt_profile,
            "message_count": message_count,
        }
    )


def build_llm_trace_summary(
    *,
    llm_profile: str,
    output_kind: str,
    duration_ms: int | None = None,
    finish_reason: str | None = None,
    stream: bool = False,
    usage: object | None = None,
) -> dict[str, Any]:
    """Return a safe LLM-call summary for agent tracing."""

    usage_counts: dict[str, int | None] | None = None
    if usage is not None:
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        usage_counts = {
            "input": input_tokens,
            "output": output_tokens,
            "total": total_tokens,
        }

    payload: dict[str, Any] = {
        "llm_profile": llm_profile,
        "output_kind": output_kind,
        "stream": stream,
        "duration_ms": duration_ms,
        "finish_reason": finish_reason,
    }
    if usage_counts is not None:
        payload["usage_counts"] = usage_counts
    return sanitize_metadata(payload)


def build_descriptor_trace_summary(descriptor: AgentDescriptor) -> dict[str, Any]:
    """Return a safe static descriptor summary for startup or health tracing."""

    return sanitize_metadata(
        {
            "name": descriptor.name,
            "type": descriptor.type,
            "enabled": descriptor.enabled,
            "display_name": descriptor.display_name,
            "llm_profile": descriptor.llm_profile,
            "supported_usecase_count": len(descriptor.supported_usecases),
            "supported_strategy_count": len(descriptor.supported_strategies),
        }
    )


def build_health_trace_summary(health: AgentHealthResult) -> dict[str, Any]:
    """Return a safe health summary for tracing or logging."""

    return sanitize_metadata(
        {
            "agent_name": health.agent_name,
            "agent_type": health.agent_type,
            "status": health.status,
            "enabled": health.enabled,
            "configured_llm_profile": health.configured_llm_profile,
            "prompt_profile": health.prompt_profile,
            "memory_required": health.memory_required,
            "tools_required": health.tools_required,
            "streaming_supported": health.streaming_supported,
        }
    )


def build_error_trace_summary(error: BaseException) -> dict[str, Any]:
    """Return a safe error summary without provider or stack payloads."""

    normalized = normalize_agent_error(error)
    return sanitize_metadata(
        {
            "code": normalized.code,
            "message": normalized.message,
            "retryable": normalized.retryable,
            "metadata": normalized.metadata,
        }
    )


def build_memory_candidate_trace_summary(
    candidates: tuple[MemoryCandidate, ...] | list[MemoryCandidate],
    *,
    warnings: tuple[AgentWarning, ...] | list[AgentWarning] = (),
) -> dict[str, Any]:
    """Return a safe summary of emitted memory candidates."""

    return sanitize_metadata(
        {
            "candidate_count": len(candidates),
            "memory_types": sorted({candidate.memory_type for candidate in candidates}),
            "scopes": sorted({candidate.scope for candidate in candidates}),
            "warning_count": len(warnings),
        }
    )


def build_review_trace_summary(review: AgentReviewResult) -> dict[str, Any]:
    """Return a safe summary of one review result."""

    return sanitize_metadata(
        {
            "status": review.status,
            "passed": review.passed,
            "score": review.score,
            "finding_count": len(review.findings),
            "suggested_revision_present": review.suggested_revision is not None,
        }
    )


__all__ = [
    "build_descriptor_trace_summary",
    "build_error_trace_summary",
    "build_health_trace_summary",
    "build_llm_trace_summary",
    "build_memory_candidate_trace_summary",
    "build_prompt_trace_summary",
    "build_request_trace_summary",
    "build_review_trace_summary",
    "build_result_trace_summary",
]