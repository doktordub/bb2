"""Strictly bounded planner/executor orchestration strategy."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from time import perf_counter
from typing import TYPE_CHECKING, Any

from app.contracts.agents import AgentPlugin
from app.contracts.context import OrchestrationContext
from app.contracts.llm import LLMRequest
from app.contracts.memory import MemoryScope, MemorySearchRequest
from app.contracts.results import OrchestrationResult as LegacyOrchestrationResult
from app.contracts.results import StreamEvent
from app.contracts.tools import ToolExecutionRequest, ToolScopes
from app.observability.events import (
    CLARIFICATION_REQUESTED,
    REQUEST_ASSESSED,
    TASK_BLOCKED,
    TASK_COMPLETED,
    TASK_LIST_GENERATED,
)
from app.orchestration.cancellation import raise_if_cancelled
from app.orchestration.errors import (
    OrchestrationDependencyUnavailableError,
    OrchestrationLimitExceededError,
    OrchestrationPlanValidationError,
)
from app.orchestration.events import OrchestrationStreamEvent
from app.orchestration.models import (
    CitationSummary,
    MemorySearchSummary,
    MemoryUpdateSummary,
    StrategyPlan,
    StrategyPlanStep,
    TaskAssessment,
    ToolCallSummary,
    sanitize_metadata,
)
from app.orchestration.prompt_inputs import PromptSection, build_prompt_messages

if TYPE_CHECKING:
    from app.orchestration.strategy import StrategyExecutionResult

_COMPONENT = "orchestration.strategy.bounded_planner"
_DEFAULT_FINAL_ANSWER = "I completed the planned steps."
_ALLOWED_ACTIONS = (
    "memory_search",
    "tool_call",
    "agent_invoke",
    "llm_call",
    "request_user_input",
    "finalize",
)
_VISUALIZATION_REQUEST_MARKERS = (
    " chart",
    "graph",
    "plot",
    "visualize",
    "visualization",
    "histogram",
    "heatmap",
    "scatter",
    "bubble",
    "pie",
    "donut",
    "treemap",
    "waterfall",
    "gantt",
    "radar",
)
_EXPLICIT_TABLE_REQUEST_RE = re.compile(
    r"\b(?:generate|create|draw|render|build|make|show|display)\s+(?:an?\s+)?table\b"
)


@dataclass(slots=True)
class BoundedPlannerStrategy:
    """Create and execute a small, validated plan within strict bounds."""

    name: str = "bounded_planner"

    async def run(
        self,
        *,
        context: OrchestrationContext,
        agents: Sequence[AgentPlugin],
    ) -> LegacyOrchestrationResult:
        strategy_result = await _run_strategy(context=context, agents=agents)
        return strategy_result.to_legacy_result(
            session_id=context.request.session_id,
            trace_id=context.request.trace_id or "unknown_trace",
            strategy_name=_strategy_name(context, default=self.name),
        )

    async def stream(
        self,
        *,
        context: OrchestrationContext,
        agents: Sequence[AgentPlugin],
    ) -> AsyncIterator[StreamEvent | OrchestrationStreamEvent]:
        result = await self.run(context=context, agents=agents)

        if result.answer:
            yield OrchestrationStreamEvent.response_delta(
                trace_id=result.trace_id or "unknown_trace",
                session_id=result.session_id,
                text=result.answer,
                metadata=_stream_metadata(result.metadata),
            )

        for tool_call in result.tool_calls:
            yield StreamEvent(event_type="tool_call_summary", data=dict(tool_call))

        yield StreamEvent(
            event_type="agent_summary",
            data={
                "agent_name": result.agent_name,
                "strategy_name": result.strategy_name,
                "llm_profile": result.llm_profile,
                **{key: value for key, value in result.metadata.items() if key != "finish_reason"},
            },
        )

        yield OrchestrationStreamEvent.response_completed(
            trace_id=result.trace_id or "unknown_trace",
            session_id=result.session_id,
            finish_reason=_read_finish_reason(result.metadata),
            metadata=_stream_metadata(result.metadata),
        )


@dataclass(frozen=True, slots=True)
class _PlannerCapabilities:
    max_plan_steps: int
    max_execute_steps: int
    max_context_bytes: int
    max_tool_loop_iterations: int
    planner_profile: str | None
    executor_profile: str | None
    memory_enabled: bool
    tools_enabled: bool
    agent_names: tuple[str, ...]
    allowed_tool_names: tuple[str, ...]
    allowed_llm_profiles: tuple[str, ...]


@dataclass(slots=True)
class _ExecutedPlanStep:
    step_type: str
    status: str
    safe_message: str
    metadata: dict[str, Any] = field(default_factory=dict)
    safe_output_text: str | None = None
    answer: str | None = None
    llm_profile: str | None = None
    tool_calls: list[ToolCallSummary] = field(default_factory=list)
    memory_searches: list[MemorySearchSummary] = field(default_factory=list)
    memory_updates: list[MemoryUpdateSummary] = field(default_factory=list)
    citations: list[CitationSummary] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    context_contributions: list[dict[str, Any]] = field(default_factory=list)
    terminal: bool = False


@dataclass(frozen=True, slots=True)
class _ResolvedTaskAssessment:
    assessment: TaskAssessment
    source: str
    agent_name: str | None
    llm_profile: str | None


async def _run_strategy(
    context: OrchestrationContext,
    *,
    agents: Sequence[AgentPlugin],
) -> StrategyExecutionResult:
    from app.orchestration.strategy_steps import (
        build_step_summary,
        finalize_strategy_result,
        require_limits,
    )

    started_at = perf_counter()
    raise_if_cancelled(_cancellation_token(context))
    strategy_name = _strategy_name(context, default="bounded_planner")
    strategy_settings = context.strategy_settings
    if strategy_settings is None:
        raise RuntimeError("Strategy settings are required for bounded-planner execution.")

    capabilities = _resolve_capabilities(context, agents=agents)
    limits = require_limits(context, component=_COMPONENT)
    agent_name = _selected_agent_name(context, agents)

    assessment_summary = None
    planner_source: str
    planner_profile: str | None
    finish_reason = "planner_completed"
    response_metadata: dict[str, Any] = {}

    if _task_first_enabled(context):
        limits.consume_step()
        assessment_started_at = perf_counter()
        assessment_result = await _assess_request(
            context,
            agents=agents,
            strategy_name=strategy_name,
            capabilities=capabilities,
        )
        assessment = assessment_result.assessment
        assessment_summary = build_step_summary(
            step_id=f"{strategy_name}:assessment",
            step_type="assessment",
            status="completed",
            duration_ms=max(int((perf_counter() - assessment_started_at) * 1000), 0),
            safe_message="Assessed the request before bounded execution.",
            metadata={
                "assessment_source": assessment_result.source,
                "assessment_agent": assessment_result.agent_name,
                "assessment_profile": assessment_result.llm_profile,
                "response_mode": assessment.response_mode,
                "request_kind": assessment.request_kind,
                "missing_input_count": len(assessment.missing_required_inputs),
                "task_count": len(assessment.suggested_task_list),
                "visualization_intent": assessment.visualization_intent,
            },
        )
        response_metadata = {
            "assessment_source": assessment_result.source,
            "request_kind": assessment.request_kind,
            "response_mode": assessment.response_mode,
            "direct_answer_eligible": assessment.direct_answer_eligible,
            "missing_required_inputs": list(assessment.missing_required_inputs),
            "required_deterministic_computations": list(assessment.required_deterministic_computations),
            "preferred_agents": list(assessment.preferred_agents),
            "preferred_tools": list(assessment.preferred_tools),
            "visualization_intent": assessment.visualization_intent,
        }
        await _record_task_execution_event(
            context,
            event_name=REQUEST_ASSESSED,
            strategy_name=strategy_name,
            agent_name=assessment_result.agent_name or agent_name,
            llm_profile=assessment_result.llm_profile,
            payload={
                "assessment_source": assessment_result.source,
                "request_kind": assessment.request_kind,
                "response_mode": assessment.response_mode,
                "missing_input_count": len(assessment.missing_required_inputs),
                "task_count": len(assessment.suggested_task_list),
                "visualization_intent": assessment.visualization_intent,
            },
        )

        if assessment.response_mode == "direct_answer":
            return finalize_strategy_result(
                answer=assessment.direct_answer or _DEFAULT_FINAL_ANSWER,
                agent_name=assessment_result.agent_name or agent_name,
                llm_profile=assessment_result.llm_profile,
                finish_reason="direct_answer",
                steps=[assessment_summary],
                tool_calls=(),
                memory_searches=(),
                memory_updates=(),
                citations=(),
                metadata={
                    **response_metadata,
                    "duration_ms": max(int((perf_counter() - started_at) * 1000), 0),
                    "finish_reason": "direct_answer",
                },
            )
        if assessment.response_mode == "request_user_input":
            await _record_task_execution_event(
                context,
                event_name=CLARIFICATION_REQUESTED,
                strategy_name=strategy_name,
                agent_name=assessment_result.agent_name or agent_name,
                llm_profile=assessment_result.llm_profile,
                payload={
                    "request_kind": assessment.request_kind,
                    "missing_required_inputs": list(assessment.missing_required_inputs),
                    "pending_task_count": 0,
                },
            )
            await _record_task_execution_event(
                context,
                event_name=TASK_BLOCKED,
                strategy_name=strategy_name,
                agent_name=assessment_result.agent_name or agent_name,
                llm_profile=assessment_result.llm_profile,
                payload={
                    "reason": "needs_user_input",
                    "missing_required_inputs": list(assessment.missing_required_inputs),
                    "pending_task_count": 0,
                },
                status="blocked",
            )
            return finalize_strategy_result(
                answer=assessment.clarification_question or _DEFAULT_FINAL_ANSWER,
                agent_name=assessment_result.agent_name or agent_name,
                llm_profile=assessment_result.llm_profile,
                finish_reason="needs_user_input",
                steps=[assessment_summary],
                tool_calls=(),
                memory_searches=(),
                memory_updates=(),
                citations=(),
                metadata={
                    **response_metadata,
                    "needs_user_input": True,
                    "duration_ms": max(int((perf_counter() - started_at) * 1000), 0),
                    "finish_reason": "needs_user_input",
                },
            )

        if assessment.suggested_task_list:
            plan = _plan_from_assessment(assessment)
            planner_source = "task_assessment"
            planner_profile = assessment_result.llm_profile
        else:
            plan, planner_source, planner_profile = await _build_plan(
                context,
                strategy_name=strategy_name,
                agent_name=agent_name,
                capabilities=capabilities,
                assessment=assessment,
            )
    else:
        limits.consume_step()
        plan_started_at = perf_counter()
        plan, planner_source, planner_profile = await _build_plan(
            context,
            strategy_name=strategy_name,
            agent_name=agent_name,
            capabilities=capabilities,
        )
        _validate_plan(plan, capabilities=capabilities)
        plan_step_summary = build_step_summary(
            step_id=f"{strategy_name}:plan",
            step_type="plan",
            status="completed",
            duration_ms=max(int((perf_counter() - plan_started_at) * 1000), 0),
            safe_message="Built and validated a bounded execution plan.",
            metadata={
                "planner_source": planner_source,
                "planner_profile": planner_profile,
                "plan_id": plan.plan_id,
                "plan_step_count": len(plan.steps),
                "plan_actions": list(plan.action_types),
            },
        )
    if _task_first_enabled(context):
        plan_started_at = perf_counter()
        _validate_plan(plan, capabilities=capabilities)
        plan_step_summary = build_step_summary(
            step_id=f"{strategy_name}:plan",
            step_type="plan",
            status="completed",
            duration_ms=max(int((perf_counter() - plan_started_at) * 1000), 0),
            safe_message="Built and validated a bounded execution plan.",
            metadata={
                "planner_source": planner_source,
                "planner_profile": planner_profile,
                "plan_id": plan.plan_id,
                "plan_step_count": len(plan.steps),
                "plan_actions": list(plan.action_types),
            },
        )
        await _record_task_execution_event(
            context,
            event_name=TASK_LIST_GENERATED,
            strategy_name=strategy_name,
            agent_name=agent_name,
            llm_profile=planner_profile,
            payload={
                "planner_source": planner_source,
                "plan_id": plan.plan_id,
                "plan_step_count": len(plan.steps),
                "plan_actions": list(plan.action_types),
            },
        )

    tool_calls: list[ToolCallSummary] = []
    memory_searches: list[MemorySearchSummary] = []
    memory_updates: list[MemoryUpdateSummary] = []
    citations: list[CitationSummary] = []
    artifacts: list[dict[str, Any]] = []
    context_contributions: list[dict[str, Any]] = []
    executed_summaries: list[Any] = []
    execution_outputs: dict[str, str] = {}
    last_output_text: str | None = None
    resolved_llm_profile = planner_profile
    tool_loop_iterations = 0
    answer: str | None = None

    for plan_step in plan.steps:
        raise_if_cancelled(_cancellation_token(context))
        limits.consume_step()
        if plan_step.action_type == "tool_call":
            tool_loop_iterations += 1
            if tool_loop_iterations > capabilities.max_tool_loop_iterations:
                raise OrchestrationLimitExceededError(
                    "The bounded planner exceeded the configured tool loop limit."
                )
        else:
            tool_loop_iterations = 0

        step_started_at = perf_counter()
        executed = await _execute_plan_step(
            plan_step,
            context=context,
            agents=agents,
            strategy_name=strategy_name,
            selected_agent_name=agent_name,
            capabilities=capabilities,
            execution_outputs=execution_outputs,
            last_output_text=last_output_text,
        )
        duration_ms = max(int((perf_counter() - step_started_at) * 1000), 0)
        executed_summaries.append(
            build_step_summary(
                step_id=plan_step.step_id,
                step_type=executed.step_type,
                status=executed.status,
                duration_ms=duration_ms,
                safe_message=executed.safe_message,
                metadata=executed.metadata,
            )
        )
        tool_calls.extend(executed.tool_calls)
        memory_searches.extend(executed.memory_searches)
        memory_updates.extend(executed.memory_updates)
        citations.extend(executed.citations)
        artifacts.extend(executed.artifacts)
        context_contributions.extend(executed.context_contributions)
        if executed.safe_output_text is not None:
            execution_outputs[plan_step.step_id] = executed.safe_output_text
            last_output_text = executed.safe_output_text
        if executed.llm_profile is not None:
            resolved_llm_profile = executed.llm_profile
        if executed.answer is not None:
            answer = executed.answer
        if executed.terminal:
            if executed.step_type == "request_user_input":
                finish_reason = "needs_user_input"
                response_metadata["needs_user_input"] = True
                await _record_task_execution_event(
                    context,
                    event_name=CLARIFICATION_REQUESTED,
                    strategy_name=strategy_name,
                    agent_name=agent_name,
                    llm_profile=resolved_llm_profile,
                    payload={
                        "step_id": plan_step.step_id,
                        "pending_task_count": max(len(plan.steps) - len(executed_summaries), 0),
                    },
                )
                await _record_task_execution_event(
                    context,
                    event_name=TASK_BLOCKED,
                    strategy_name=strategy_name,
                    agent_name=agent_name,
                    llm_profile=resolved_llm_profile,
                    payload={
                        "reason": "needs_user_input",
                        "step_id": plan_step.step_id,
                        "pending_task_count": max(len(plan.steps) - len(executed_summaries), 0),
                    },
                    status="blocked",
                )
            break

    duration_ms = max(int((perf_counter() - started_at) * 1000), 0)
    if _task_first_enabled(context) and finish_reason != "needs_user_input":
        await _record_task_execution_event(
            context,
            event_name=TASK_COMPLETED,
            strategy_name=strategy_name,
            agent_name=agent_name,
            llm_profile=resolved_llm_profile,
            payload={
                "finish_reason": finish_reason,
                "plan_id": plan.plan_id,
                "plan_step_count": len(plan.steps),
                "executed_step_count": len(executed_summaries),
                "artifact_count": len(artifacts),
                "tool_call_count": len(tool_calls),
                "memory_search_count": len(memory_searches),
                "memory_update_count": len(memory_updates),
            },
        )
    return finalize_strategy_result(
        answer=answer or last_output_text or _DEFAULT_FINAL_ANSWER,
        agent_name=agent_name,
        llm_profile=resolved_llm_profile,
        finish_reason=finish_reason,
        steps=[item for item in (assessment_summary, plan_step_summary, *executed_summaries) if item is not None],
        tool_calls=tool_calls,
        memory_searches=memory_searches,
        memory_updates=memory_updates,
        citations=citations,
        artifacts=artifacts,
        context_contributions=context_contributions,
        metadata={
            **response_metadata,
            "planner_source": planner_source,
            "plan_id": plan.plan_id,
            "plan_step_count": len(plan.steps),
            "executed_step_count": len(executed_summaries),
            "plan_actions": list(plan.action_types),
            "tool_call_count": len(tool_calls),
            "memory_search_count": len(memory_searches),
            "memory_update_count": len(memory_updates),
            "artifact_count": len(artifacts),
            "context_contribution_count": len(context_contributions),
            "duration_ms": duration_ms,
            "finish_reason": finish_reason,
            **({"artifacts": artifacts} if artifacts else {}),
            **({"context_contributions": context_contributions} if context_contributions else {}),
            **({"safe_goal": plan.safe_goal} if plan.safe_goal is not None else {}),
        },
    )


async def _build_plan(
    context: OrchestrationContext,
    *,
    strategy_name: str,
    agent_name: str | None,
    capabilities: _PlannerCapabilities,
    assessment: TaskAssessment | None = None,
) -> tuple[StrategyPlan, str, str | None]:
    from app.orchestration.strategy_steps import run_llm_completion_step

    raw_plan = context.request.metadata.get("planner_plan")
    if raw_plan is not None:
        return _parse_plan(raw_plan), "request_metadata", None

    if capabilities.planner_profile is None:
        raise OrchestrationPlanValidationError(
            "The bounded planner requires a planner LLM profile or request metadata plan."
        )

    response = await run_llm_completion_step(
        context,
        component=_COMPONENT,
        request=LLMRequest(
            component=_COMPONENT,
            profile=capabilities.planner_profile,
            messages=_build_planner_messages(
                context,
                capabilities=capabilities,
                assessment=assessment,
            ),
            metadata={
                "strategy_name": strategy_name,
                "agent_name": agent_name,
                "allowed_actions": list(_ALLOWED_ACTIONS),
            },
        ),
        agent_name=agent_name,
        strategy_name=strategy_name,
    )
    return _parse_plan(response.text), "llm", response.profile


async def _execute_plan_step(
    plan_step: StrategyPlanStep,
    *,
    context: OrchestrationContext,
    agents: Sequence[AgentPlugin],
    strategy_name: str,
    selected_agent_name: str | None,
    capabilities: _PlannerCapabilities,
    execution_outputs: Mapping[str, str],
    last_output_text: str | None,
) -> _ExecutedPlanStep:
    from app.orchestration.strategy_steps import (
        agent_result_answer,
        build_citation_summaries_from_agent_result,
        build_memory_update_summaries_from_agent_result,
        build_tool_call_summaries_from_agent_result,
        run_agent_step,
        run_llm_completion_step,
        run_memory_search_step,
        run_tool_call_step,
    )

    if plan_step.action_type == "memory_search":
        limit = _positive_int(plan_step.inputs.get("limit")) or 3
        request = MemorySearchRequest(
            text=_required_step_text(plan_step.inputs.get("query") or plan_step.inputs.get("text"), step=plan_step),
            scope=_build_memory_scope(context, agent_name=selected_agent_name),
            limit=limit,
            include_document_chunks=True,
            metadata={"planner_step_id": plan_step.step_id, "strategy_name": strategy_name},
        )
        memory_result, memory_summary = await run_memory_search_step(
            context,
            component=_COMPONENT,
            request=request,
            agent_name=selected_agent_name,
            strategy_name=strategy_name,
            summary_source="planner",
        )
        return _ExecutedPlanStep(
            step_type="memory_search",
            status="completed",
            safe_message=f"Retrieved {memory_summary.result_count} memory result(s).",
            metadata={"result_count": memory_summary.result_count, "limit": limit},
            safe_output_text=_memory_output_text(memory_result),
            memory_searches=[memory_summary],
        )

    if plan_step.action_type == "tool_call":
        tool_name = _required_text(
            _read_optional_text(plan_step.inputs.get("tool_name")) or plan_step.name,
            message=f"Planner step '{plan_step.step_id}' must select a tool name.",
        )
        tool_definition = await context.tools.get_tool(tool_name, context)
        tool_result, tool_summary = await run_tool_call_step(
            context,
            component=_COMPONENT,
            request=ToolExecutionRequest(
                tool_name=tool_name,
                arguments=_tool_arguments(plan_step),
                scopes=_build_tool_scopes(context, agent_name=selected_agent_name),
                metadata={"planner_step_id": plan_step.step_id, "strategy_name": strategy_name},
            ),
            agent_name=selected_agent_name,
            strategy_name=strategy_name,
            tool_definition=tool_definition,
        )
        if not tool_result.success:
            raise OrchestrationDependencyUnavailableError(
                tool_result.error or f"Planner tool step '{plan_step.step_id}' failed."
            )
        return _ExecutedPlanStep(
            step_type="tool_call",
            status="completed",
            safe_message=tool_summary.safe_message or "Planner tool step completed.",
            metadata={"tool_name": tool_name, "success": tool_result.success},
            safe_output_text=_tool_output_text(tool_result),
            tool_calls=[tool_summary],
        )

    if plan_step.action_type == "agent_invoke":
        agent = _resolve_agent(plan_step, agents=agents, default_agent_name=selected_agent_name)
        agent_result = await run_agent_step(
            context,
            component=_COMPONENT,
            agent=agent,
            strategy_name=strategy_name,
        )
        artifacts = [dict(item) for item in agent_result.artifacts]
        context_contributions = [dict(item) for item in agent_result.context_contributions]
        return _ExecutedPlanStep(
            step_type="agent_invoke",
            status="completed",
            safe_message="Planner agent step completed.",
            metadata={
                "agent_name": agent_result.agent_name or agent.name,
                "tool_call_count": len(agent_result.tool_intents),
                "memory_update_count": len(agent_result.memory_candidates),
                "artifact_count": len(artifacts),
                "context_contribution_count": len(context_contributions),
            },
            safe_output_text=_safe_text(agent_result_answer(agent_result)),
            llm_profile=_read_optional_text(agent_result.llm_profile),
            tool_calls=list(build_tool_call_summaries_from_agent_result(agent_result)),
            memory_updates=list(build_memory_update_summaries_from_agent_result(agent_result)),
            citations=list(build_citation_summaries_from_agent_result(agent_result)),
            artifacts=artifacts,
            context_contributions=context_contributions,
        )

    if plan_step.action_type == "llm_call":
        prompt = _required_step_text(
            plan_step.inputs.get("prompt") or plan_step.inputs.get("message"),
            step=plan_step,
        )
        profile = _read_optional_text(plan_step.inputs.get("profile")) or capabilities.executor_profile
        response = await run_llm_completion_step(
            context,
            component=_COMPONENT,
            request=LLMRequest(
                component=_COMPONENT,
                profile=profile,
                messages=_build_executor_messages(
                    context,
                    instruction=prompt,
                    execution_outputs=execution_outputs,
                    last_output_text=last_output_text,
                    max_context_bytes=capabilities.max_context_bytes,
                ),
                metadata={"planner_step_id": plan_step.step_id, "strategy_name": strategy_name},
            ),
            agent_name=selected_agent_name,
            strategy_name=strategy_name,
        )
        return _ExecutedPlanStep(
            step_type="llm_call",
            status="completed",
            safe_message="Planner LLM execution step completed.",
            metadata={"llm_profile": response.profile},
            safe_output_text=_safe_text(response.text),
            llm_profile=response.profile,
        )

    if plan_step.action_type == "request_user_input":
        question = _required_text(
            _read_optional_text(
                plan_step.inputs.get("question")
                or plan_step.inputs.get("clarification_question")
                or plan_step.inputs.get("answer")
            ),
            message=f"Planner step '{plan_step.step_id}' must include a clarification question.",
        )
        missing_inputs = _coerce_identifier_tuple(
            plan_step.inputs.get("missing_required_inputs") or plan_step.inputs.get("missing_inputs")
        )
        return _ExecutedPlanStep(
            step_type="request_user_input",
            status="completed",
            safe_message="Planner paused execution to request one follow-up input.",
            metadata={
                "missing_required_inputs": list(missing_inputs),
            },
            safe_output_text=question,
            answer=question,
            terminal=True,
        )

    answer = _resolve_finalize_answer(
        plan_step,
        execution_outputs=execution_outputs,
        last_output_text=last_output_text,
    )
    return _ExecutedPlanStep(
        step_type="finalize",
        status="completed",
        safe_message="Planner execution finalized a safe answer.",
        metadata={"used_last_output": answer == last_output_text},
        safe_output_text=answer,
        answer=answer,
        terminal=True,
    )


def _validate_plan(
    plan: StrategyPlan,
    *,
    capabilities: _PlannerCapabilities,
) -> None:
    if not plan.steps:
        raise OrchestrationPlanValidationError("The bounded planner returned an empty plan.")
    if len(plan.steps) > capabilities.max_plan_steps:
        raise OrchestrationPlanValidationError(
            "The bounded planner exceeded the configured max plan step limit."
        )
    if len(plan.steps) > capabilities.max_execute_steps:
        raise OrchestrationPlanValidationError(
            "The bounded planner exceeded the configured max execute step limit."
        )
    if plan.steps[-1].action_type not in {"finalize", "request_user_input"}:
        raise OrchestrationPlanValidationError(
            "The bounded planner must end with a finalize or request_user_input step."
        )

    seen_step_ids: set[str] = set()
    for step in plan.steps:
        if step.step_id in seen_step_ids:
            raise OrchestrationPlanValidationError(
                f"The bounded planner returned duplicate step_id '{step.step_id}'."
            )
        for dependency in step.depends_on:
            if dependency not in seen_step_ids:
                raise OrchestrationPlanValidationError(
                    f"Planner step '{step.step_id}' depends on unknown step '{dependency}'."
                )
        seen_step_ids.add(step.step_id)
        _validate_plan_step(step, capabilities=capabilities)

    for index, step in enumerate(plan.steps[:-1]):
        if step.action_type == "request_user_input":
            raise OrchestrationPlanValidationError(
                "The bounded planner may only use request_user_input as the terminal step."
            )


def _validate_plan_step(
    step: StrategyPlanStep,
    *,
    capabilities: _PlannerCapabilities,
) -> None:
    if step.action_type == "memory_search":
        if not capabilities.memory_enabled:
            raise OrchestrationPlanValidationError(
                f"Planner step '{step.step_id}' cannot use memory_search when memory is disabled."
            )
        _required_step_text(step.inputs.get("query") or step.inputs.get("text"), step=step)
        return

    if step.action_type == "tool_call":
        if not capabilities.tools_enabled:
            raise OrchestrationPlanValidationError(
                f"Planner step '{step.step_id}' cannot use tool_call when tools are disabled."
            )
        tool_name = _required_text(
            _read_optional_text(step.inputs.get("tool_name")) or step.name,
            message=f"Planner step '{step.step_id}' must select a tool name.",
        )
        if tool_name not in capabilities.allowed_tool_names:
            raise OrchestrationPlanValidationError(
                f"Planner step '{step.step_id}' references unsupported tool '{tool_name}'."
            )
        return

    if step.action_type == "agent_invoke":
        agent_name = _read_optional_text(step.inputs.get("agent_name")) or step.name
        if agent_name not in capabilities.agent_names:
            raise OrchestrationPlanValidationError(
                f"Planner step '{step.step_id}' references unknown agent '{agent_name}'."
            )
        return

    if step.action_type == "llm_call":
        profile = _read_optional_text(step.inputs.get("profile")) or capabilities.executor_profile
        if profile is None or profile not in capabilities.allowed_llm_profiles:
            raise OrchestrationPlanValidationError(
                f"Planner step '{step.step_id}' references unsupported llm profile '{profile}'."
            )
        _required_step_text(step.inputs.get("prompt") or step.inputs.get("message"), step=step)
        return

    if step.action_type == "request_user_input":
        _required_text(
            _read_optional_text(
                step.inputs.get("question")
                or step.inputs.get("clarification_question")
                or step.inputs.get("answer")
            ),
            message=f"Planner step '{step.step_id}' must include a clarification question.",
        )


def _resolve_capabilities(
    context: OrchestrationContext,
    *,
    agents: Sequence[AgentPlugin],
) -> _PlannerCapabilities:
    strategy_settings = context.strategy_settings
    if strategy_settings is None:
        raise RuntimeError("Strategy settings are required for bounded-planner capability resolution.")
    defaults = context.settings.defaults if context.settings is not None else None
    usecase_settings = _usecase_settings(context)
    planner_profile = strategy_settings.planner_llm_profile or _read_optional_text(context.config.get("llm.defaults.profile"))
    executor_profile = (
        strategy_settings.executor_llm_profile
        or (None if usecase_settings is None else usecase_settings.llm_profile)
        or strategy_settings.llm_profile
        or _read_optional_text(context.runtime_metadata.get("llm_profile"))
        or _read_optional_text(context.config.get("llm.defaults.profile"))
    )
    allowed_llm_profiles = tuple(
        dict.fromkeys(
            profile
            for profile in (
                planner_profile,
                executor_profile,
                strategy_settings.llm_profile,
                None if usecase_settings is None else usecase_settings.llm_profile,
                _read_optional_text(context.runtime_metadata.get("llm_profile")),
                _read_optional_text(context.config.get("llm.defaults.profile")),
            )
            if profile is not None
        )
    )
    return _PlannerCapabilities(
        max_plan_steps=_required_positive_limit(
            strategy_settings.max_plan_steps,
            message="The bounded planner requires max_plan_steps.",
        ),
        max_execute_steps=_required_positive_limit(
            strategy_settings.max_execute_steps,
            message="The bounded planner requires max_execute_steps.",
        ),
        max_context_bytes=_required_positive_limit(
            strategy_settings.max_context_bytes
            or (defaults.max_context_bytes if defaults is not None else 8_000),
            message="The bounded planner requires max_context_bytes.",
        ),
        max_tool_loop_iterations=_required_positive_limit(
            strategy_settings.max_tool_loop_iterations
            or (defaults.max_tool_loop_iterations if defaults is not None else 1),
            message="The bounded planner requires max_tool_loop_iterations.",
        ),
        planner_profile=planner_profile,
        executor_profile=executor_profile,
        memory_enabled=bool(strategy_settings.memory_enabled)
        and bool(usecase_settings.memory.enabled if usecase_settings is not None else True),
        tools_enabled=bool(strategy_settings.tools_enabled)
        and bool(usecase_settings.tools.enabled if usecase_settings is not None else True),
        agent_names=tuple(agent.name for agent in agents),
        allowed_tool_names=_allowed_tool_names(context),
        allowed_llm_profiles=allowed_llm_profiles,
    )


def _build_planner_messages(
    context: OrchestrationContext,
    *,
    capabilities: _PlannerCapabilities,
    assessment: TaskAssessment | None = None,
) -> list[Any]:
    sections = [
        PromptSection(
            title="Planner contract",
            body=(
                "Return JSON only. The JSON object must contain plan_id and steps. "
                "Each step must contain step_id, action_type, name, and inputs. "
                "The last step must use action_type=finalize."
            ),
        ),
        PromptSection(
            title="Allowed actions",
            body="\n".join(f"- {item}" for item in _ALLOWED_ACTIONS),
        ),
        PromptSection(
            title="Available capabilities",
            body=(
                f"Agents: {', '.join(capabilities.agent_names) or 'none'}\n"
                f"Tools: {', '.join(capabilities.allowed_tool_names) or 'none'}\n"
                f"Planner profile: {capabilities.planner_profile or 'none'}\n"
                f"Executor profile: {capabilities.executor_profile or 'none'}\n"
                f"Max plan steps: {capabilities.max_plan_steps}\n"
                f"Max execute steps: {capabilities.max_execute_steps}"
            ),
        ),
    ]
    if assessment is not None:
        sections.append(
            PromptSection(
                title="Assessment summary",
                body=(
                    f"Request kind: {assessment.request_kind}\n"
                    f"Response mode: {assessment.response_mode}\n"
                    f"Preferred agents: {', '.join(assessment.preferred_agents) or 'none'}\n"
                    f"Preferred tools: {', '.join(assessment.preferred_tools) or 'none'}\n"
                    f"Deterministic computations: {', '.join(assessment.required_deterministic_computations) or 'none'}\n"
                    f"Visualization intent: {'yes' if assessment.visualization_intent else 'no'}"
                ),
            )
        )
    return build_prompt_messages(
        user_request=context.request.message,
        sections=sections,
        system_prompt=(
            "You are a bounded planner. Produce a short plan that uses only the allowed actions, "
            "stays within the configured limits, and ends with finalize."
        ),
    )


def _build_executor_messages(
    context: OrchestrationContext,
    *,
    instruction: str,
    execution_outputs: Mapping[str, str],
    last_output_text: str | None,
    max_context_bytes: int,
) -> list[Any]:
    sections = [
        PromptSection(title="Execution instruction", body=instruction),
        PromptSection(
            title="Execution context",
            body=_bounded_execution_context(
                execution_outputs,
                last_output_text=last_output_text,
                max_context_bytes=max_context_bytes,
            ),
        ),
    ]
    return build_prompt_messages(
        user_request=context.request.message,
        sections=sections,
        system_prompt=(
            "Use the provided safe execution context to answer the user. "
            "Do not mention hidden planning details."
        ),
    )


def _bounded_execution_context(
    execution_outputs: Mapping[str, str],
    *,
    last_output_text: str | None,
    max_context_bytes: int,
) -> str:
    parts: list[str] = []
    for step_id, text in execution_outputs.items():
        parts.append(f"{step_id}: {text}")
    if not parts and last_output_text is not None:
        parts.append(last_output_text)
    rendered = "\n".join(parts) or "No prior step output was recorded."
    return _trim_bytes(rendered, max_context_bytes)


def _resolve_finalize_answer(
    plan_step: StrategyPlanStep,
    *,
    execution_outputs: Mapping[str, str],
    last_output_text: str | None,
) -> str:
    explicit_answer = _read_optional_text(plan_step.inputs.get("answer"))
    if explicit_answer is not None:
        return explicit_answer
    template = _read_optional_text(plan_step.inputs.get("template"))
    if template is not None:
        try:
            return template.format(
                last_output=last_output_text or "",
                safe_goal=_read_optional_text(plan_step.inputs.get("safe_goal")) or "",
            ).strip() or _DEFAULT_FINAL_ANSWER
        except (IndexError, KeyError, ValueError):
            return template
    if last_output_text is not None:
        return last_output_text
    if execution_outputs:
        return tuple(execution_outputs.values())[-1]
    return _DEFAULT_FINAL_ANSWER


def _parse_plan(raw_plan: object) -> StrategyPlan:
    try:
        if isinstance(raw_plan, StrategyPlan):
            return raw_plan
        if isinstance(raw_plan, Mapping):
            return StrategyPlan.from_mapping(raw_plan)
        if isinstance(raw_plan, str):
            normalized = _strip_json_fence(raw_plan)
            try:
                decoded = json.loads(normalized)
            except json.JSONDecodeError as exc:
                raise OrchestrationPlanValidationError("The planner did not return valid JSON.") from exc
            if not isinstance(decoded, Mapping):
                raise OrchestrationPlanValidationError("The planner must return a JSON object.")
            return StrategyPlan.from_mapping(decoded)
    except (TypeError, ValueError) as exc:
        raise OrchestrationPlanValidationError("The planner returned an invalid bounded plan.") from exc
    raise OrchestrationPlanValidationError("The planner returned an unsupported plan payload.")


def _strip_json_fence(value: str) -> str:
    normalized = value.strip()
    if not normalized.startswith("```"):
        return normalized
    lines = normalized.splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return normalized


def _selected_agent_name(
    context: OrchestrationContext,
    agents: Sequence[AgentPlugin],
) -> str | None:
    runtime_agent = _read_optional_text(context.runtime_metadata.get("agent_name"))
    if runtime_agent is not None:
        return runtime_agent
    if context.strategy_settings is not None and context.strategy_settings.default_agent is not None:
        return context.strategy_settings.default_agent
    if agents:
        return agents[0].name
    return None


def _resolve_agent(
    plan_step: StrategyPlanStep,
    *,
    agents: Sequence[AgentPlugin],
    default_agent_name: str | None,
) -> AgentPlugin:
    requested_name = _read_optional_text(plan_step.inputs.get("agent_name")) or plan_step.name
    if requested_name == "step" and default_agent_name is not None:
        requested_name = default_agent_name
    for agent in agents:
        if agent.name == requested_name:
            return agent
    if default_agent_name is not None:
        for agent in agents:
            if agent.name == default_agent_name:
                return agent
    raise OrchestrationPlanValidationError(
        f"Planner step '{plan_step.step_id}' references unknown agent '{requested_name}'."
    )


def _allowed_tool_names(context: OrchestrationContext) -> tuple[str, ...]:
    names: list[str] = []
    strategy_settings = context.strategy_settings
    if strategy_settings is not None:
        names.extend(strategy_settings.tools.allowed_tools)
    if context.settings is not None and context.request.usecase is not None:
        usecase = context.settings.usecases.get(context.request.usecase)
        if usecase is not None:
            names.extend(usecase.tools.allowed_tools)
    unique: list[str] = []
    for name in names:
        normalized = _read_optional_text(name)
        if normalized is None or normalized in unique:
            continue
        unique.append(normalized)
    return tuple(unique)


def _build_memory_scope(
    context: OrchestrationContext,
    *,
    agent_name: str | None,
) -> MemoryScope:
    _ = agent_name
    runtime = context.runtime
    usecase_settings = _usecase_settings(context)
    project_id = runtime.project_id if runtime is not None else None
    if usecase_settings is not None and usecase_settings.memory.allowed_project_ids:
        if project_id not in usecase_settings.memory.allowed_project_ids:
            project_id = usecase_settings.memory.default_project_id
    elif usecase_settings is not None and project_id is None:
        project_id = usecase_settings.memory.default_project_id
    return MemoryScope(
        project_id=project_id,
        tenant_id=runtime.tenant_id if runtime is not None else None,
    )


def _build_tool_scopes(
    context: OrchestrationContext,
    *,
    agent_name: str | None,
) -> ToolScopes:
    runtime = context.runtime
    return ToolScopes(
        user_id=context.request.user_id,
        project_id=runtime.project_id if runtime is not None else None,
        tenant_id=runtime.tenant_id if runtime is not None else None,
        session_id=context.request.session_id,
        agent_name=agent_name,
        usecase=context.request.usecase,
    )


def _tool_arguments(plan_step: StrategyPlanStep) -> dict[str, Any]:
    raw_arguments = plan_step.inputs.get("arguments")
    if isinstance(raw_arguments, Mapping):
        return sanitize_metadata(raw_arguments)
    return sanitize_metadata(
        {
            key: value
            for key, value in plan_step.inputs.items()
            if key not in {"tool_name"}
        }
    )


async def _assess_request(
    context: OrchestrationContext,
    *,
    agents: Sequence[AgentPlugin],
    strategy_name: str,
    capabilities: _PlannerCapabilities,
) -> _ResolvedTaskAssessment:
    from app.agents.models import AgentOutputFormat, AgentTask
    from app.orchestration.strategy_steps import run_agent_step

    raw_assessment = context.request.metadata.get("task_assessment")
    if raw_assessment is not None:
        assessment = _apply_visualization_request_fallback(
            TaskAssessment.from_payload(raw_assessment),
            message=context.request.message,
        )
        return _ResolvedTaskAssessment(
            assessment=assessment,
            source="request_metadata",
            agent_name=None,
            llm_profile=None,
        )

    assessment_agent = _resolve_assessment_agent(context, agents=agents)
    context_items = (
        PromptSection(
            title="Allowed execution capabilities",
            body=(
                f"Agents: {', '.join(capabilities.agent_names) or 'none'}\n"
                f"Tools: {', '.join(capabilities.allowed_tool_names) or 'none'}\n"
                f"Memory enabled: {'yes' if capabilities.memory_enabled else 'no'}\n"
                "Visualization intent should stay false unless the user explicitly requests a "
                "chart, graph, plot, or table artifact."
            ),
        ),
    )
    task = AgentTask(
        type="task_assessment",
        instruction=(
            "Assess the current request and choose exactly one response_mode: direct_answer, "
            "request_user_input, or planned_execution."
        ),
        expected_outputs=(
            "request_kind",
            "response_mode",
            "direct_answer or clarification_question or suggested_task_list",
        ),
        safe_goal="Select the smallest safe path before any tool, memory, or chart work runs.",
    )
    output_format = AgentOutputFormat(
        kind="task_assessment",
        schema_name="task_assessment_contract",
        require_json=True,
        max_items=capabilities.max_plan_steps,
    )
    try:
        result = await run_agent_step(
            context,
            component=_COMPONENT,
            agent=assessment_agent,
            strategy_name=strategy_name,
            context_items=context_items,
            available_tools=capabilities.allowed_tool_names,
            task=task,
            constraints=(
                "Return JSON only.",
                "Choose exactly one response_mode.",
                "Use only the listed agents and tools in suggested_task_list.",
                "Do not include chain-of-thought, hidden reasoning, or raw prompt content.",
            ),
            output_format=output_format,
            metadata={"assessment_only": True},
        )
    except Exception:
        if _looks_like_visualization_request_message(context.request.message):
            return _ResolvedTaskAssessment(
                assessment=_build_visualization_request_assessment(),
                source="heuristic",
                agent_name=assessment_agent.name,
                llm_profile=None,
            )
        raise
    assessment_payload = result.metadata.get("task_assessment")
    if assessment_payload is None:
        assessment_payload = result.answer
    assessment = _apply_visualization_request_fallback(
        TaskAssessment.from_payload(assessment_payload),
        message=context.request.message,
    )
    return _ResolvedTaskAssessment(
        assessment=assessment,
        source="agent",
        agent_name=result.agent_name or assessment_agent.name,
        llm_profile=_read_optional_text(result.llm_profile),
    )


def _apply_visualization_request_fallback(
    assessment: TaskAssessment,
    *,
    message: str,
) -> TaskAssessment:
    if assessment.visualization_intent or not _looks_like_visualization_request_message(message):
        return assessment
    return _build_visualization_request_assessment(
        required_deterministic_computations=assessment.required_deterministic_computations,
        preferred_tools=assessment.preferred_tools,
        safe_goal=assessment.safe_goal,
        metadata={
            **assessment.metadata,
            "assessment_fallback": "visualization_request_heuristic",
        },
    )


def _build_visualization_request_assessment(
    *,
    required_deterministic_computations: Sequence[str] = (),
    preferred_tools: Sequence[str] = (),
    safe_goal: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> TaskAssessment:
    return TaskAssessment(
        request_kind="visualization_request",
        response_mode="planned_execution",
        direct_answer_eligible=False,
        direct_answer=None,
        clarification_question=None,
        missing_required_inputs=(),
        required_deterministic_computations=tuple(required_deterministic_computations),
        suggested_task_list=(
            StrategyPlanStep(
                step_id="chart_1",
                action_type="agent_invoke",
                name="chart_agent",
                inputs={},
            ),
        ),
        preferred_agents=("chart_agent",),
        preferred_tools=tuple(preferred_tools),
        visualization_intent=True,
        safe_goal=safe_goal,
        metadata={} if metadata is None else dict(metadata),
    )


def _looks_like_visualization_request_message(message: str) -> bool:
    lowered = message.casefold()
    if any(marker in lowered for marker in _VISUALIZATION_REQUEST_MARKERS):
        return True
    return _EXPLICIT_TABLE_REQUEST_RE.search(lowered) is not None


def _plan_from_assessment(assessment: TaskAssessment) -> StrategyPlan:
    steps = list(assessment.suggested_task_list)
    if not steps:
        raise OrchestrationPlanValidationError(
            "Task assessment planned_execution mode requires suggested_task_list."
        )
    if steps[-1].action_type not in {"finalize", "request_user_input"}:
        steps.append(
            StrategyPlanStep(
                step_id=_next_generated_step_id(steps, prefix="finalize"),
                action_type="finalize",
                name="return_answer",
                inputs={},
            )
        )
    return StrategyPlan(
        plan_id=_read_optional_text(assessment.metadata.get("plan_id")) or "task_assessment_plan",
        steps=tuple(steps),
        safe_goal=assessment.safe_goal,
    )


def _task_first_enabled(context: OrchestrationContext) -> bool:
    usecase_settings = _usecase_settings(context)
    if usecase_settings is None:
        return False
    return _read_optional_text(usecase_settings.metadata.get("routing_mode")) == "task_first"


def _usecase_settings(context: OrchestrationContext) -> Any:
    if context.settings is None or context.request.usecase is None:
        return None
    return context.settings.usecases.get(context.request.usecase)


def _resolve_assessment_agent(
    context: OrchestrationContext,
    *,
    agents: Sequence[AgentPlugin],
) -> AgentPlugin:
    usecase_settings = _usecase_settings(context)
    configured_name = None
    if usecase_settings is not None:
        configured_name = _read_optional_text(usecase_settings.metadata.get("assessment_agent"))
    configured_name = configured_name or "task_execution_agent"
    for agent in agents:
        if agent.name == configured_name:
            return agent
    raise OrchestrationPlanValidationError(
        f"Task-first bounded planning requires an assessment agent named '{configured_name}'."
    )


def _next_generated_step_id(
    steps: Sequence[StrategyPlanStep],
    *,
    prefix: str,
) -> str:
    existing = {step.step_id for step in steps}
    index = 1
    candidate = f"{prefix}_{index}"
    while candidate in existing:
        index += 1
        candidate = f"{prefix}_{index}"
    return candidate


def _coerce_identifier_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return ()
    normalized: list[str] = []
    for item in value:
        text = _read_optional_text(item)
        if text is not None:
            normalized.append(text)
    return tuple(normalized)


def _memory_output_text(result: Any) -> str | None:
    safe_parts: list[str] = []
    for item in list(getattr(result, "results", []))[:3]:
        text = _read_optional_text(getattr(item, "text", None))
        if text is not None:
            safe_parts.append(text)
    if not safe_parts:
        return None
    return "\n".join(safe_parts)


def _tool_output_text(result: Any) -> str | None:
    for item in getattr(result, "content", []):
        text = _read_optional_text(getattr(item, "text", None))
        if text is not None:
            return text
    if getattr(result, "summary", None) is not None:
        return _read_optional_text(result.summary.safe_message)
    return _read_optional_text(getattr(result, "error", None))


def _coerce_tool_call_summaries(items: Sequence[Mapping[str, Any]]) -> list[ToolCallSummary]:
    return [ToolCallSummary.from_mapping(item) for item in items]


def _coerce_memory_update_summaries(items: Sequence[Mapping[str, Any]]) -> list[MemoryUpdateSummary]:
    return [MemoryUpdateSummary.from_mapping(item) for item in items]


def _coerce_citation_summaries(items: Sequence[Mapping[str, Any]]) -> list[CitationSummary]:
    return [CitationSummary.from_mapping(item) for item in items]


def _required_step_text(value: object, *, step: StrategyPlanStep) -> str:
    return _required_text(
        _read_optional_text(value),
        message=f"Planner step '{step.step_id}' requires a non-empty text input.",
    )


def _required_text(value: str | None, *, message: str) -> str:
    if value is None:
        raise OrchestrationPlanValidationError(message)
    return value


def _required_positive_limit(value: int | None, *, message: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise OrchestrationPlanValidationError(message)
    return value


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value <= 0:
        return None
    return value


def _trim_bytes(value: str, max_context_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_context_bytes:
        return value
    trimmed = encoded[: max_context_bytes - 3].decode("utf-8", errors="ignore").rstrip()
    return f"{trimmed}..."


def _strategy_name(context: OrchestrationContext, *, default: str) -> str:
    runtime_value = _read_optional_text(context.runtime_metadata.get("strategy_name"))
    if runtime_value is not None:
        return runtime_value
    return default


def _read_finish_reason(metadata: Mapping[str, Any]) -> str:
    finish_reason = _read_optional_text(metadata.get("finish_reason"))
    return finish_reason or "planner_completed"


def _stream_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key in {"planner_source", "plan_id", "plan_step_count", "executed_step_count", "finish_reason"}
    }


async def _record_task_execution_event(
    context: OrchestrationContext,
    *,
    event_name: str,
    strategy_name: str,
    agent_name: str | None,
    llm_profile: str | None,
    payload: Mapping[str, Any],
    status: str = "completed",
) -> None:
    recorder = context.observability
    if recorder is None:
        return

    await recorder.record(
        event_type="orchestration",
        event_name=event_name,
        component=_COMPONENT,
        status=status,
        trace_id=context.request.trace_id,
        session_id=context.request.session_id,
        user_id=context.request.user_id,
        usecase=context.request.usecase,
        agent_name=agent_name,
        strategy_name=strategy_name,
        llm_profile=llm_profile,
        payload=sanitize_metadata(payload),
    )


def _safe_text(value: object) -> str | None:
    return _read_optional_text(value)


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _cancellation_token(context: OrchestrationContext) -> object | None:
    runtime = context.runtime
    if runtime is not None and runtime.cancellation_token is not None:
        return runtime.cancellation_token
    return context.request.metadata.get("cancellation_token")