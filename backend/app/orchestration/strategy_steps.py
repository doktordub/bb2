"""Reusable gateway and summary helpers for strategy step execution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING
from typing import Any, Literal, cast

from app.agents.models import AgentOutputFormat, AgentRunResult, AgentTask
from app.contracts.agents import AgentHandle, AgentPlugin, build_run_request_from_context
from app.contracts.context import OrchestrationContext
from app.contracts.llm import LLMMessage, LLMRequest, LLMResponse
from app.contracts.memory import MemoryScope, MemorySearchRequest, MemorySearchResult, MemoryWrite, MemoryWriteResult
from app.contracts.policy import PolicyRequest
from app.contracts.tools import ToolDefinition, ToolExecutionRequest, ToolExecutionResult
from app.orchestration.limits import OrchestrationLimitTracker
from app.orchestration.memory_intents import build_memory_search_summary
from app.orchestration.models import CitationSummary, MemorySearchSummary, MemoryUpdateSummary, OrchestrationStepSummary, ToolCallSummary, sanitize_metadata
from app.orchestration.prompt_inputs import PromptSection
from app.orchestration.tool_intents import build_tool_policy_metadata, tool_result_safe_text

if TYPE_CHECKING:
    from app.orchestration.strategy import StrategyExecutionResult


def require_limits(context: OrchestrationContext, *, component: str) -> OrchestrationLimitTracker:
    if context.limits is None:
        raise RuntimeError(f"Orchestration limits are required for {component}.")
    return context.limits


async def run_llm_completion_step(
    context: OrchestrationContext,
    *,
    component: str,
    request: LLMRequest,
    agent_name: str | None,
    strategy_name: str,
    action: Literal["llm.complete", "llm.stream"] = "llm.complete",
) -> LLMResponse:
    limits = require_limits(context, component=component)
    limits.consume_llm_call()
    if request.profile is not None:
        await context.policy.require_allowed(
            PolicyRequest(
                action=action,
                component=component,
                resource=request.profile,
                scope=_policy_scope(context, agent_name=agent_name, strategy_name=strategy_name),
            ),
            context,
        )
    return await context.llm.complete(request, context)


async def run_memory_search_step(
    context: OrchestrationContext,
    *,
    component: str,
    request: MemorySearchRequest,
    agent_name: str | None,
    strategy_name: str,
    summary_source: str = "memory",
) -> tuple[MemorySearchResult, MemorySearchSummary]:
    limits = require_limits(context, component=component)
    limits.consume_memory_search()
    policy_scope_memory = _resolved_memory_search_policy_scope(context, request.scope)
    policy_scope = _policy_scope_with_memory(
        context,
        agent_name=agent_name,
        strategy_name=strategy_name,
        memory_scope=policy_scope_memory,
    )
    await context.policy.require_allowed(
        PolicyRequest(
            action="memory.search",
            component=component,
            resource="retrieval_context",
            scope=policy_scope,
            metadata={"scope": policy_scope_memory.summary()},
        ),
        context,
    )
    result = await context.memory.search(request, context)
    return result, build_memory_search_summary(
        result,
        source=summary_source,
        context_item_count=len(result.results),
    )


async def run_memory_write_step(
    context: OrchestrationContext,
    *,
    component: str,
    memory_write: MemoryWrite,
    agent_name: str | None,
    strategy_name: str,
) -> tuple[MemoryWriteResult, MemoryUpdateSummary]:
    limits = require_limits(context, component=component)
    limits.consume_step()
    limits.consume_memory_write()
    policy_scope = _policy_scope_with_memory(
        context,
        agent_name=agent_name,
        strategy_name=strategy_name,
        memory_scope=memory_write.scope,
    )
    await context.policy.require_allowed(
        PolicyRequest(
            action="memory.upsert",
            component=component,
            resource=memory_write.memory_type,
            scope=policy_scope,
            metadata={"scope": memory_write.scope.summary()},
        ),
        context,
    )
    result = await context.memory.upsert(memory_write, context)
    summary = MemoryUpdateSummary(
        operation=result.operation,
        status=result.status,
        safe_message=_memory_write_safe_message(result, memory_write),
        metadata={
            "changed": result.changed,
            "memory_id_present": result.memory_id is not None,
            "memory_type": memory_write.memory_type,
            "scope": memory_write.scope.summary(),
        },
    )
    return result, summary


async def run_tool_call_step(
    context: OrchestrationContext,
    *,
    component: str,
    request: ToolExecutionRequest,
    agent_name: str | None,
    strategy_name: str,
    tool_definition: ToolDefinition | None = None,
) -> tuple[ToolExecutionResult, ToolCallSummary]:
    limits = require_limits(context, component=component)
    limits.consume_tool_call()
    await context.policy.require_allowed(
        PolicyRequest(
            action="tool.execute",
            component=component,
            resource=request.tool_name,
            scope=_policy_scope(context, agent_name=agent_name, strategy_name=strategy_name),
            metadata=build_tool_policy_metadata(tool_definition),
        ),
        context,
    )
    result = await context.tools.execute(request, context)
    summary = ToolCallSummary(
        tool_name=result.tool_name,
        status=result.status,
        safe_message=tool_result_safe_text(result),
        duration_ms=result.duration_ms,
        metadata={"success": result.success},
    )
    return result, summary


async def run_agent_step(
    context: OrchestrationContext,
    *,
    component: str,
    agent: AgentPlugin,
    strategy_name: str,
    context_items: Sequence[PromptSection] = (),
    tool_context: Sequence[PromptSection] = (),
    llm_followup_messages: Sequence[LLMMessage] = (),
    available_tools: Sequence[str] | None = None,
    task: AgentTask | None = None,
    constraints: Sequence[str] = (),
    output_format: AgentOutputFormat | None = None,
    metadata: Mapping[str, Any] | None = None,
    llm_profile: str | None = None,
) -> AgentRunResult:
    if context.limits is not None:
        context.limits.check_turn_duration()
    await context.policy.require_allowed(
        PolicyRequest(
            action="agent.invoke",
            component=component,
            resource=agent.name,
            scope=_policy_scope(
                context,
                agent_name=agent.name,
                strategy_name=strategy_name,
            ),
        ),
        context,
    )
    request = build_run_request_from_context(
        context,
        agent_name=agent.name,
        llm_profile=llm_profile,
        strategy_name=strategy_name,
        context_items=context_items,
        tool_context=tool_context,
        llm_followup_messages=llm_followup_messages,
        available_tools=available_tools,
        task=task,
        constraints=constraints,
        output_format=output_format,
        metadata=metadata,
    )
    return await cast(AgentHandle, agent).run(request=request, context=context)


def agent_result_answer(result: AgentRunResult) -> str:
    if result.answer is not None:
        return result.answer
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


def build_agent_result_metadata(result: AgentRunResult) -> dict[str, Any]:
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
        metadata["output_item_count"] = len(result.output_items)
    if result.artifacts:
        metadata["artifacts"] = [dict(item) for item in result.artifacts]
        metadata.setdefault("artifact_count", len(result.artifacts))
    if result.context_contributions:
        metadata["context_contributions"] = [dict(item) for item in result.context_contributions]
        metadata.setdefault("context_contribution_count", len(result.context_contributions))
    return sanitize_metadata(metadata)


def build_tool_call_summaries_from_agent_result(
    result: AgentRunResult,
) -> tuple[ToolCallSummary, ...]:
    summaries: list[ToolCallSummary] = []
    for intent in result.tool_intents:
        reason = _read_optional_text(intent.metadata.get("reason"))
        summaries.append(
            ToolCallSummary(
                tool_name=intent.tool_name,
                status=_read_optional_text(intent.metadata.get("status")) or "planned",
                safe_message=(
                    _read_optional_text(intent.metadata.get("safe_message"))
                    or reason
                    or f"Prepared logical tool intent for {intent.tool_name}."
                ),
                metadata={
                    "argument_keys": tuple(sorted(str(key) for key in intent.arguments.keys())),
                    **({"reason": reason} if reason is not None else {}),
                },
            )
        )
    return tuple(summaries)


def build_memory_update_summaries_from_agent_result(
    result: AgentRunResult,
) -> tuple[MemoryUpdateSummary, ...]:
    summaries: list[MemoryUpdateSummary] = []
    for candidate in result.memory_candidates:
        summaries.append(
            MemoryUpdateSummary(
                operation="candidate",
                status="proposed",
                safe_message=(
                    candidate.reason
                    or f"Prepared one {candidate.scope.replace('_', ' ')} memory candidate."
                ),
                metadata={
                    "memory_type": candidate.memory_type,
                    "scope": candidate.scope,
                    "stable_key_present": candidate.stable_key is not None,
                    "tag_count": len(candidate.tags),
                },
            )
        )
    return tuple(summaries)


def build_citation_summaries_from_agent_result(
    result: AgentRunResult,
) -> tuple[CitationSummary, ...]:
    summaries: list[CitationSummary] = []
    for item in result.output_items:
        label = item.source_label or _read_optional_text(item.metadata.get("section_title"))
        if label is None:
            continue
        summaries.append(
            CitationSummary(
                label=label,
                source=item.source_label,
                metadata=item.metadata,
            )
        )
    return tuple(summaries)


def build_step_summary(
    *,
    step_id: str,
    step_type: str,
    status: str,
    duration_ms: int | None = None,
    safe_message: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> OrchestrationStepSummary:
    return OrchestrationStepSummary(
        step_id=step_id,
        step_type=step_type,
        status=status,
        duration_ms=duration_ms,
        safe_message=safe_message,
        metadata=sanitize_metadata(metadata),
    )


def finalize_strategy_result(
    *,
    answer: str,
    agent_name: str | None,
    llm_profile: str | None,
    finish_reason: str = "stop",
    steps: Iterable[OrchestrationStepSummary] = (),
    tool_calls: Iterable[ToolCallSummary] = (),
    memory_searches: Iterable[MemorySearchSummary] = (),
    memory_updates: Iterable[MemoryUpdateSummary] = (),
    citations: Iterable[CitationSummary] = (),
    artifacts: Iterable[Mapping[str, Any]] = (),
    context_contributions: Iterable[Mapping[str, Any]] = (),
    metadata: Mapping[str, Any] | None = None,
) -> StrategyExecutionResult:
    from app.orchestration.strategy import StrategyExecutionResult

    return StrategyExecutionResult(
        answer=answer,
        agent_name=agent_name,
        llm_profile=llm_profile,
        finish_reason=finish_reason,
        steps=tuple(steps),
        tool_calls=tuple(tool_calls),
        memory_searches=tuple(memory_searches),
        memory_updates=tuple(memory_updates),
        citations=tuple(citations),
        artifacts=tuple(dict(item) for item in artifacts if isinstance(item, Mapping)),
        context_contributions=tuple(
            dict(item) for item in context_contributions if isinstance(item, Mapping)
        ),
        metadata=sanitize_metadata(metadata),
    )


def _policy_scope(
    context: OrchestrationContext,
    *,
    agent_name: str | None,
    strategy_name: str,
) -> dict[str, Any]:
    return {
        "usecase_name": context.request.usecase,
        "agent_name": agent_name,
        "strategy_name": strategy_name,
    }


def _policy_scope_with_memory(
    context: OrchestrationContext,
    *,
    agent_name: str | None,
    strategy_name: str,
    memory_scope: MemoryScope,
) -> dict[str, Any]:
    scope = _policy_scope(
        context,
        agent_name=agent_name,
        strategy_name=strategy_name,
    )
    summary = memory_scope.summary()
    scope_type = _read_optional_text(summary.get("scope_type")) or "global"
    usecase_name = _read_optional_text(memory_scope.usecase) or context.request.usecase
    scope.update(
        {
            "memory_scope": scope_type,
            "tenant_id": memory_scope.tenant_id,
            "project_id": memory_scope.project_id,
            "user_id": memory_scope.user_id,
            "session_id": memory_scope.session_id,
            "usecase": usecase_name,
            "source_id": memory_scope.source_id,
            "document_id": memory_scope.document_id,
            "tags": list(memory_scope.tags),
        }
    )
    return {key: value for key, value in scope.items() if value is not None}


def _resolved_memory_search_policy_scope(
    context: OrchestrationContext,
    scope: MemoryScope,
) -> MemoryScope:
    from app.config.view import get_memory_settings
    from app.memory.scopes import resolve_memory_scope

    default_scope = get_memory_settings(context.config).defaults.default_scope
    return resolve_memory_scope(scope, context=context, default_scope=default_scope)


def _memory_write_safe_message(
    result: MemoryWriteResult,
    memory_write: MemoryWrite,
) -> str:
    if result.record is not None and result.record.summary:
        return result.record.summary
    if result.status in {"ok", "completed", "created", "updated"}:
        scope_type = memory_write.scope.summary().get("scope_type")
        if isinstance(scope_type, str) and scope_type:
            return f"Stored one {scope_type.replace('_', ' ')} memory update."
        return "Stored one durable memory update."
    return "Memory update completed."


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None