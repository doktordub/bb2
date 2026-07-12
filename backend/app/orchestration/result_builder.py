"""Builders and compatibility adapters for orchestration-owned results."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.contracts.results import OrchestrationResult as LegacyOrchestrationResult
from app.orchestration.models import (
    CitationSummary,
    MemorySearchSummary,
    MemoryUpdateSummary,
    OrchestrationResult,
    OrchestrationStepSummary,
    ToolCallSummary,
    sanitize_metadata,
)
from app.orchestration.state_delta import WorkflowStateDelta, workflow_state_delta_to_dict
from app.visualization.context_selector import coerce_context_contribution
from app.visualization.models import ChartArtifact, ContextContribution


def build_orchestration_result(
    *,
    answer: str,
    session_id: str,
    trace_id: str,
    usecase: str,
    strategy_name: str,
    agent_name: str | None = None,
    llm_profile: str | None = None,
    steps: Iterable[OrchestrationStepSummary | Mapping[str, Any]] = (),
    tool_calls: Iterable[ToolCallSummary | Mapping[str, Any]] = (),
    memory_searches: Iterable[MemorySearchSummary | Mapping[str, Any]] = (),
    memory_updates: Iterable[MemoryUpdateSummary | Mapping[str, Any]] = (),
    citations: Iterable[CitationSummary | Mapping[str, Any]] = (),
    artifacts: Iterable[ChartArtifact | Mapping[str, Any]] = (),
    context_contributions: Iterable[ContextContribution | Mapping[str, Any]] = (),
    state_delta: WorkflowStateDelta | None = None,
    finish_reason: str = "stop",
    duration_ms: int | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> OrchestrationResult:
    """Build an orchestration-owned result from safe summaries or raw summary mappings."""

    return OrchestrationResult(
        answer=answer,
        session_id=session_id,
        trace_id=trace_id,
        usecase=usecase,
        strategy_name=strategy_name,
        agent_name=agent_name,
        llm_profile=llm_profile,
        steps=_coerce_step_summaries(steps),
        tool_calls=_coerce_tool_call_summaries(tool_calls),
        memory_searches=_coerce_memory_search_summaries(memory_searches),
        memory_updates=_coerce_memory_update_summaries(memory_updates),
        citations=_coerce_citation_summaries(citations),
        artifacts=_coerce_chart_artifacts(artifacts),
        context_contributions=_coerce_context_contributions(context_contributions),
        state_delta=state_delta,
        finish_reason=finish_reason,
        duration_ms=duration_ms,
        metadata=sanitize_metadata(metadata),
    )


def orchestration_result_from_contract(
    result: LegacyOrchestrationResult,
    *,
    usecase: str | None,
    state_delta: WorkflowStateDelta | None = None,
    steps: Iterable[OrchestrationStepSummary | Mapping[str, Any]] = (),
    memory_searches: Iterable[MemorySearchSummary | Mapping[str, Any]] = (),
    finish_reason: str = "stop",
    duration_ms: int | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> OrchestrationResult:
    """Adapt the current shared result contract into the orchestration-owned result model."""

    resolved_metadata = dict(result.metadata)
    if metadata is not None:
        resolved_metadata.update(metadata)

    resolved_usecase = _read_optional_text(resolved_metadata.get("usecase")) or usecase or "default_chat"
    resolved_trace_id = result.trace_id or _read_optional_text(resolved_metadata.get("trace_id")) or "unknown_trace"

    return build_orchestration_result(
        answer=result.answer,
        session_id=result.session_id,
        trace_id=resolved_trace_id,
        usecase=resolved_usecase,
        strategy_name=result.strategy_name or "unknown_strategy",
        agent_name=result.agent_name,
        llm_profile=result.llm_profile,
        steps=steps,
        tool_calls=result.tool_calls,
        memory_searches=memory_searches,
        memory_updates=result.memory_updates,
        citations=result.citations,
        artifacts=result.artifacts,
        context_contributions=result.context_contributions,
        state_delta=state_delta,
        finish_reason=finish_reason,
        duration_ms=duration_ms,
        metadata=resolved_metadata,
    )


def orchestration_result_to_contract(result: OrchestrationResult) -> LegacyOrchestrationResult:
    """Adapt the orchestration-owned result model into the current shared result contract."""

    metadata = dict(result.metadata)
    metadata["usecase"] = result.usecase
    metadata["finish_reason"] = result.finish_reason
    if result.duration_ms is not None:
        metadata["duration_ms"] = result.duration_ms
    if result.steps:
        metadata["steps"] = [item.as_dict() for item in result.steps]
    if result.memory_searches:
        metadata["memory_searches"] = [item.as_dict() for item in result.memory_searches]
    if result.state_delta is not None:
        metadata["state_delta"] = workflow_state_delta_to_dict(result.state_delta)

    return LegacyOrchestrationResult(
        answer=result.answer,
        session_id=result.session_id,
        trace_id=result.trace_id,
        agent_name=result.agent_name,
        strategy_name=result.strategy_name,
        llm_profile=result.llm_profile,
        tool_calls=[item.as_legacy_dict() for item in result.tool_calls],
        memory_updates=[item.as_legacy_dict() for item in result.memory_updates],
        citations=[item.as_legacy_dict() for item in result.citations],
        artifacts=[item.model_dump(mode="python") for item in result.artifacts],
        context_contributions=[item.model_dump(mode="python") for item in result.context_contributions],
        metadata=sanitize_metadata(metadata),
    )


def _coerce_step_summaries(
    steps: Iterable[OrchestrationStepSummary | Mapping[str, Any]],
) -> list[OrchestrationStepSummary]:
    summaries: list[OrchestrationStepSummary] = []
    for item in steps:
        summaries.append(item if isinstance(item, OrchestrationStepSummary) else OrchestrationStepSummary.from_mapping(item))
    return summaries


def _coerce_tool_call_summaries(
    items: Iterable[ToolCallSummary | Mapping[str, Any]],
) -> list[ToolCallSummary]:
    summaries: list[ToolCallSummary] = []
    for item in items:
        summaries.append(item if isinstance(item, ToolCallSummary) else ToolCallSummary.from_mapping(item))
    return summaries


def _coerce_memory_search_summaries(
    items: Iterable[MemorySearchSummary | Mapping[str, Any]],
) -> list[MemorySearchSummary]:
    summaries: list[MemorySearchSummary] = []
    for item in items:
        summaries.append(item if isinstance(item, MemorySearchSummary) else MemorySearchSummary.from_mapping(item))
    return summaries


def _coerce_memory_update_summaries(
    items: Iterable[MemoryUpdateSummary | Mapping[str, Any]],
) -> list[MemoryUpdateSummary]:
    summaries: list[MemoryUpdateSummary] = []
    for item in items:
        summaries.append(item if isinstance(item, MemoryUpdateSummary) else MemoryUpdateSummary.from_mapping(item))
    return summaries


def _coerce_citation_summaries(
    items: Iterable[CitationSummary | Mapping[str, Any]],
) -> list[CitationSummary]:
    summaries: list[CitationSummary] = []
    for item in items:
        summaries.append(item if isinstance(item, CitationSummary) else CitationSummary.from_mapping(item))
    return summaries


def _coerce_chart_artifacts(
    items: Iterable[ChartArtifact | Mapping[str, Any]],
) -> list[ChartArtifact]:
    artifacts: list[ChartArtifact] = []
    for item in items:
        artifacts.append(item if isinstance(item, ChartArtifact) else ChartArtifact.model_validate(dict(item)))
    return artifacts


def _coerce_context_contributions(
    items: Iterable[ContextContribution | Mapping[str, Any]],
) -> list[ContextContribution]:
    contributions: list[ContextContribution] = []
    for item in items:
        if isinstance(item, ContextContribution):
            contributions.append(item)
            continue
        coerced = coerce_context_contribution(item)
        if coerced is not None:
            contributions.append(coerced)
    return contributions


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None