"""Strictly bounded planner/executor orchestration strategy."""

from __future__ import annotations

import json
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
    ToolCallSummary,
    sanitize_metadata,
)
from app.orchestration.prompt_inputs import PromptSection, build_prompt_messages

if TYPE_CHECKING:
    from app.orchestration.strategy import StrategyExecutionResult

_COMPONENT = "orchestration.strategy.bounded_planner"
_DEFAULT_FINAL_ANSWER = "I completed the planned steps."
_ALLOWED_ACTIONS = ("memory_search", "tool_call", "agent_invoke", "llm_call", "finalize")


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

    tool_calls: list[ToolCallSummary] = []
    memory_searches: list[MemorySearchSummary] = []
    memory_updates: list[MemoryUpdateSummary] = []
    citations: list[CitationSummary] = []
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
        if executed.safe_output_text is not None:
            execution_outputs[plan_step.step_id] = executed.safe_output_text
            last_output_text = executed.safe_output_text
        if executed.llm_profile is not None:
            resolved_llm_profile = executed.llm_profile
        if executed.answer is not None:
            answer = executed.answer

    duration_ms = max(int((perf_counter() - started_at) * 1000), 0)
    return finalize_strategy_result(
        answer=answer or last_output_text or _DEFAULT_FINAL_ANSWER,
        agent_name=agent_name,
        llm_profile=resolved_llm_profile,
        finish_reason="planner_completed",
        steps=[plan_step_summary, *executed_summaries],
        tool_calls=tool_calls,
        memory_searches=memory_searches,
        memory_updates=memory_updates,
        citations=citations,
        metadata={
            "planner_source": planner_source,
            "plan_id": plan.plan_id,
            "plan_step_count": len(plan.steps),
            "executed_step_count": len(executed_summaries),
            "plan_actions": list(plan.action_types),
            "tool_call_count": len(tool_calls),
            "memory_search_count": len(memory_searches),
            "memory_update_count": len(memory_updates),
            "duration_ms": duration_ms,
            "finish_reason": "planner_completed",
            **({"safe_goal": plan.safe_goal} if plan.safe_goal is not None else {}),
        },
    )


async def _build_plan(
    context: OrchestrationContext,
    *,
    strategy_name: str,
    agent_name: str | None,
    capabilities: _PlannerCapabilities,
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
            messages=_build_planner_messages(context, capabilities=capabilities),
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
        return _ExecutedPlanStep(
            step_type="agent_invoke",
            status="completed",
            safe_message="Planner agent step completed.",
            metadata={
                "agent_name": agent_result.agent_name or agent.name,
                "tool_call_count": len(agent_result.tool_intents),
                "memory_update_count": len(agent_result.memory_candidates),
            },
            safe_output_text=_safe_text(agent_result_answer(agent_result)),
            llm_profile=_read_optional_text(agent_result.llm_profile),
            tool_calls=list(build_tool_call_summaries_from_agent_result(agent_result)),
            memory_updates=list(build_memory_update_summaries_from_agent_result(agent_result)),
            citations=list(build_citation_summaries_from_agent_result(agent_result)),
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
    if plan.steps[-1].action_type != "finalize":
        raise OrchestrationPlanValidationError(
            "The bounded planner must end with a finalize step."
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


def _resolve_capabilities(
    context: OrchestrationContext,
    *,
    agents: Sequence[AgentPlugin],
) -> _PlannerCapabilities:
    strategy_settings = context.strategy_settings
    if strategy_settings is None:
        raise RuntimeError("Strategy settings are required for bounded-planner capability resolution.")
    defaults = context.settings.defaults if context.settings is not None else None
    planner_profile = strategy_settings.planner_llm_profile or _read_optional_text(context.config.get("llm.defaults.profile"))
    executor_profile = (
        strategy_settings.executor_llm_profile
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
        memory_enabled=bool(strategy_settings.memory_enabled),
        tools_enabled=bool(strategy_settings.tools_enabled),
        agent_names=tuple(agent.name for agent in agents),
        allowed_tool_names=_allowed_tool_names(context),
        allowed_llm_profiles=allowed_llm_profiles,
    )


def _build_planner_messages(
    context: OrchestrationContext,
    *,
    capabilities: _PlannerCapabilities,
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
    runtime = context.runtime
    return MemoryScope(
        user_id=context.request.user_id,
        project_id=runtime.project_id if runtime is not None else None,
        tenant_id=runtime.tenant_id if runtime is not None else None,
        session_id=context.request.session_id,
        agent_name=agent_name,
        usecase=context.request.usecase,
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