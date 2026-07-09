"""Tool-assisted orchestration strategy."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal

from app.agents.errors import AgentLLMError
from app.agents.result_builder import build_run_result
from app.contracts.agents import AgentPlugin
from app.contracts.context import OrchestrationContext
from app.contracts.results import OrchestrationResult as LegacyOrchestrationResult
from app.contracts.results import StreamEvent
from app.contracts.tools import ToolDefinition, ToolExecutionRequest, ToolExecutionResult, ToolScopes
from app.orchestration.cancellation import raise_if_cancelled
from app.orchestration.errors import AgentNotFoundError, OrchestrationLimitExceededError
from app.orchestration.events import OrchestrationStreamEvent
from app.orchestration.models import ToolCallSummary
from app.orchestration.prompt_inputs import PromptSection
from app.orchestration.strategy_steps import (
    agent_result_answer,
    build_agent_result_metadata,
    build_citation_summaries_from_agent_result,
    build_step_summary,
    finalize_strategy_result,
    require_limits,
    run_agent_step,
    run_tool_call_step,
)
from app.orchestration.tool_intents import ToolIntent, build_default_tool_arguments, tool_result_safe_text

if TYPE_CHECKING:
    from app.orchestration.strategy import StrategyExecutionResult

_COMPONENT = "orchestration.strategy.tool_assisted"
_TOOL_TRIGGER_PREFIX = "tool:"
_DIRECT_SEARCH_HINTS = ("weather", "forecast", "temperature", "search the web", "search web")
_WEB_SEARCH_ONLY_TOOLS = ("websearch.search",)


@dataclass(slots=True)
class ToolAssistedStrategy:
    """Run one bounded logical tool call, then synthesize a final answer."""

    name: str = "tool_assisted"

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
            strategy_name=_strategy_name(context),
        )

    async def stream(
        self,
        *,
        context: OrchestrationContext,
        agents: Sequence[AgentPlugin],
    ) -> AsyncIterator[StreamEvent | OrchestrationStreamEvent]:
        result = await self.run(context=context, agents=agents)

        for tool_call in result.tool_calls:
            yield StreamEvent(event_type="tool_call_summary", data=dict(tool_call))

        if result.answer:
            yield OrchestrationStreamEvent.response_delta(
                trace_id=result.trace_id or "unknown_trace",
                session_id=result.session_id,
                text=result.answer,
            )

        yield StreamEvent(
            event_type="agent_summary",
            data={
                "agent_name": result.agent_name,
                "strategy_name": result.strategy_name,
                "llm_profile": result.llm_profile,
                **{
                    key: value
                    for key, value in result.metadata.items()
                    if key != "finish_reason"
                },
            },
        )
        yield OrchestrationStreamEvent.response_completed(
            trace_id=result.trace_id or "unknown_trace",
            session_id=result.session_id,
            finish_reason=_read_finish_reason(result.metadata),
        )


async def _run_strategy(
    context: OrchestrationContext,
    *,
    agents: Sequence[AgentPlugin],
) -> StrategyExecutionResult:
    started_at = perf_counter()
    raise_if_cancelled(_cancellation_token(context))
    limits = require_limits(context, component=_COMPONENT)
    limits.consume_step()
    strategy_name = _strategy_name(context)
    agent = _selected_agent(context, agents)
    agent_name = agent.name
    available_tools = _unique_tool_names(_configured_tool_names(context, agent_name=agent_name))
    shortcut_intent = _resolve_direct_tool_intent(context, available_tools=available_tools)
    direct_answer_agent = _resolve_direct_answer_agent(
        context,
        agents=agents,
        available_tools=available_tools,
        shortcut_intent=shortcut_intent,
    )
    planning_agent = direct_answer_agent or agent
    planning_agent_name = planning_agent.name
    llm_profile = await _resolve_llm_profile(
        context,
        agent_name=planning_agent_name,
        action="llm.complete",
    )
    if direct_answer_agent is not None:
        planning_result = await run_agent_step(
            context,
            component=_COMPONENT,
            agent=planning_agent,
            strategy_name=strategy_name,
            llm_profile=llm_profile,
            metadata={
                "tool_loop_iterations": int(context.metadata.get("tool_loop_iterations", 0)),
                "direct_answer_shortcut": True,
                "tool_planning_agent": agent_name,
            },
        )
    elif shortcut_intent is None:
        planning_result = await run_agent_step(
            context,
            component=_COMPONENT,
            agent=planning_agent,
            strategy_name=strategy_name,
            available_tools=available_tools,
            llm_profile=llm_profile,
            metadata={"tool_loop_iterations": int(context.metadata.get("tool_loop_iterations", 0))},
        )
    else:
        planning_result = build_run_result(
            status="completed",
            answer=None,
            agent_name=planning_agent_name,
            llm_profile=llm_profile,
            tool_intents=(shortcut_intent,),
            metadata={
                "response_mode": "tool_intents",
                "tool_intent_count": 1,
                "planner_bypassed": True,
            },
        )

    if direct_answer_agent is not None and planning_result.tool_intents:
        raise OrchestrationLimitExceededError(
            "The tool-assisted direct-answer shortcut cannot request logical tools."
        )

    if len(planning_result.tool_intents) > 1:
        raise OrchestrationLimitExceededError(
            "The tool-assisted strategy allows at most one logical tool intent per turn."
        )

    final_result = planning_result
    tool_result = None
    tool_summary = None
    if planning_result.tool_intents:
        tool_intent = planning_result.tool_intents[0]
        tool_definition = await context.tools.get_tool(tool_intent.tool_name, context)
        tool_result, tool_summary = await _execute_tool(
            context,
            agent_name=agent_name,
            tool_definition=tool_definition,
            tool_intent=tool_intent,
        )
        raise_if_cancelled(_cancellation_token(context))
        if shortcut_intent is not None:
            final_result = _build_direct_tool_summary_result(
                agent_name=agent_name,
                llm_profile=llm_profile,
                tool_result=tool_result,
            )
        else:
            try:
                final_result = await run_agent_step(
                    context,
                    component=_COMPONENT,
                    agent=agent,
                    strategy_name=strategy_name,
                    available_tools=available_tools,
                    tool_context=(_tool_result_section(tool_result),),
                    llm_profile=llm_profile,
                    metadata={"tool_loop_iterations": int(context.metadata.get("tool_loop_iterations", 0))},
                )
            except AgentLLMError:
                if not _supports_direct_tool_summary(tool_result):
                    raise
                final_result = _build_direct_tool_summary_result(
                    agent_name=agent_name,
                    llm_profile=llm_profile,
                    tool_result=tool_result,
                )
        if final_result.tool_intents:
            raise OrchestrationLimitExceededError(
                "The tool-assisted strategy requested another tool after tool results were provided."
            )
    raise_if_cancelled(_cancellation_token(context))

    duration_ms = int((perf_counter() - started_at) * 1000)
    metadata = {
        **build_agent_result_metadata(final_result),
        "planned_tool_intent_count": len(planning_result.tool_intents),
        "tool_call_count": 0 if tool_summary is None else 1,
        "tool_loop_iterations": int(context.metadata.get("tool_loop_iterations", 0)),
        "duration_ms": duration_ms,
    }
    if direct_answer_agent is not None:
        metadata.update(
            {
                "direct_answer_shortcut": True,
                "direct_answer_agent": planning_agent_name,
                "tool_planning_agent": agent_name,
            }
        )
    steps = [
        build_step_summary(
            step_id=f"{strategy_name}:agent_plan",
            step_type="agent",
            status="completed",
            safe_message=(
                "Answered directly through the configured direct-answer agent."
                if direct_answer_agent is not None
                else (
                "Generated a bounded logical tool intent."
                if planning_result.tool_intents
                else "Answered directly without a tool call."
                )
            ),
            metadata={
                "agent_name": planning_result.agent_name or planning_agent_name,
                "llm_profile": planning_result.llm_profile or llm_profile,
                "tool_intent_count": len(planning_result.tool_intents),
                **(
                    {
                        "direct_answer_shortcut": True,
                        "tool_planning_agent": agent_name,
                    }
                    if direct_answer_agent is not None
                    else {}
                ),
            },
        )
    ]
    if tool_summary is not None:
        steps.append(
            build_step_summary(
                step_id=f"{strategy_name}:tool",
                step_type="tool",
                status=tool_summary.status,
                duration_ms=tool_summary.duration_ms,
                safe_message=tool_summary.safe_message,
                metadata={
                    "tool_name": tool_summary.tool_name,
                    **dict(tool_summary.metadata),
                },
            )
        )
        steps.append(
            build_step_summary(
                step_id=f"{strategy_name}:agent_finalize",
                step_type="agent",
                status="completed",
                duration_ms=duration_ms,
                safe_message="Generated the final tool-assisted answer.",
                metadata={
                    "agent_name": final_result.agent_name or agent_name,
                    "llm_profile": final_result.llm_profile or llm_profile,
                    "tool_call_count": 1,
                    "tool_loop_iterations": int(context.metadata.get("tool_loop_iterations", 0)),
                },
            )
        )
    return finalize_strategy_result(
        answer=agent_result_answer(final_result),
        agent_name=final_result.agent_name or planning_agent_name,
        llm_profile=final_result.llm_profile or llm_profile,
        finish_reason=_read_finish_reason(metadata),
        steps=steps,
        tool_calls=[] if tool_summary is None else [tool_summary],
        citations=build_citation_summaries_from_agent_result(final_result),
        metadata=metadata,
    )


async def _execute_tool(
    context: OrchestrationContext,
    *,
    agent_name: str,
    tool_definition: ToolDefinition | None,
    tool_intent: ToolIntent,
) -> tuple[ToolExecutionResult, ToolCallSummary]:
    _consume_tool_loop_iteration(context)
    signature = f"{tool_intent.tool_name}:{sorted(tool_intent.arguments.items())!r}"
    seen_signatures = context.metadata.setdefault("tool_signatures", [])
    if signature in seen_signatures:
        raise OrchestrationLimitExceededError(
            "The tool-assisted strategy repeated the same logical tool call."
        )
    seen_signatures.append(signature)

    return await run_tool_call_step(
        context,
        component=_COMPONENT,
        request=ToolExecutionRequest(
            tool_name=tool_intent.tool_name,
            arguments=tool_intent.arguments,
            scopes=ToolScopes(
                user_id=context.request.user_id,
                project_id=None if context.runtime is None else context.runtime.project_id,
                tenant_id=None if context.runtime is None else context.runtime.tenant_id,
                session_id=context.request.session_id,
                agent_name=agent_name,
                usecase=context.request.usecase,
            ),
            metadata={
                "strategy_name": _strategy_name(context),
                "agent_name": agent_name,
                "query": tool_intent.query,
            },
        ),
        agent_name=agent_name,
        strategy_name=_strategy_name(context),
        tool_definition=tool_definition,
    )


async def _resolve_llm_profile(
    context: OrchestrationContext,
    *,
    agent_name: str,
    action: Literal["llm.complete", "llm.stream"],
) -> str | None:
    override = _request_profile_override(context)
    if override is not None:
        return override

    profile = (
        _runtime_value(context, "llm_profile")
        or (None if context.strategy_settings is None else context.strategy_settings.llm_profile)
        or _read_optional_str(context.config.get("llm.defaults.profile"))
    )
    return profile


def _configured_tool_names(
    context: OrchestrationContext,
    *,
    agent_name: str,
) -> list[str]:
    configured: list[str] = []
    if context.strategy_settings is not None:
        configured.extend(context.strategy_settings.tools.allowed_tools)
    if context.settings is not None and context.request.usecase is not None:
        usecase = context.settings.usecases.get(context.request.usecase)
        if usecase is not None:
            configured.extend(usecase.tools.allowed_tools)
    configured.extend(_read_string_list(context.config.get(f"agents.{agent_name}.allowed_tools")))
    return configured


def _unique_tool_names(values: Sequence[str]) -> tuple[str, ...]:
    unique: list[str] = []
    for item in values:
        tool_name = _read_optional_str(item)
        if tool_name is None or tool_name in unique:
            continue
        unique.append(tool_name)
    return tuple(unique)


def _resolve_direct_tool_intent(
    context: OrchestrationContext,
    *,
    available_tools: Sequence[str],
) -> ToolIntent | None:
    if tuple(available_tools) != _WEB_SEARCH_ONLY_TOOLS:
        return None

    message = _read_optional_str(context.request.message)
    if message is None:
        return None

    lowered = message.casefold()
    if not any(term in lowered for term in _DIRECT_SEARCH_HINTS):
        return None

    return ToolIntent(
        tool_name="websearch.search",
        arguments=build_default_tool_arguments("websearch.search", message),
        query=message,
        metadata={"reason": "single_search_short_circuit"},
    )


def _resolve_direct_answer_agent(
    context: OrchestrationContext,
    *,
    agents: Sequence[AgentPlugin],
    available_tools: Sequence[str],
    shortcut_intent: ToolIntent | None,
) -> AgentPlugin | None:
    if shortcut_intent is not None:
        return None
    if tuple(available_tools) != _WEB_SEARCH_ONLY_TOOLS:
        return None

    message = _read_optional_str(context.request.message)
    if message is None:
        return None

    lowered = message.casefold()
    if any(term in lowered for term in _DIRECT_SEARCH_HINTS):
        return None

    direct_agent_name = _configured_direct_answer_agent_name(context)
    if direct_agent_name is None:
        return None

    for agent in agents:
        if agent.name == direct_agent_name:
            return agent
    return None


def _configured_direct_answer_agent_name(context: OrchestrationContext) -> str | None:
    if context.settings is None:
        return None

    direct_settings = context.settings.strategies.get("direct_agent")
    if direct_settings is None or not direct_settings.enabled:
        return None

    usecase_name = _read_optional_str(context.request.usecase)
    if direct_settings.allowed_usecases and usecase_name not in direct_settings.allowed_usecases:
        return None

    agent_name = _read_optional_str(direct_settings.default_agent)
    if agent_name is None:
        return None

    if usecase_name is None:
        return agent_name

    usecase = context.settings.usecases.get(usecase_name)
    if usecase is None:
        return None
    if usecase.allowed_agents and agent_name not in usecase.allowed_agents:
        return None
    return agent_name


def _selected_agent_name(
    context: OrchestrationContext,
    agents: Sequence[AgentPlugin],
) -> str:
    return _selected_agent(context, agents).name


def _selected_agent(
    context: OrchestrationContext,
    agents: Sequence[AgentPlugin],
) -> AgentPlugin:
    preferred_name = _runtime_value(context, "agent_name")
    if preferred_name is not None:
        for agent in agents:
            if agent.name == preferred_name:
                return agent
    if agents:
        return agents[0]
    raise AgentNotFoundError("No agent is configured for the selected strategy.")


def _request_profile_override(context: OrchestrationContext) -> str | None:
    for key in ("llm_profile_override", "requested_llm_profile"):
        value = _read_optional_str(context.request.metadata.get(key))
        if value is not None:
            return value
    return None


def _strategy_name(context: OrchestrationContext) -> str:
    return _runtime_value(context, "strategy_name") or "tool_assisted"


def _runtime_value(context: OrchestrationContext, key: str) -> str | None:
    value = context.runtime_metadata.get(key)
    return _read_optional_str(value)


def _read_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    normalized: list[str] = []
    for item in value:
        text = _read_optional_str(item)
        if text is not None:
            normalized.append(text)
    return normalized


def _consume_tool_loop_iteration(context: OrchestrationContext) -> int:
    configured_limit = None
    if context.strategy_settings is not None:
        configured_limit = (
            context.strategy_settings.tools.max_tool_loop_iterations
            or context.strategy_settings.max_tool_loop_iterations
        )
    if configured_limit is None and context.settings is not None:
        configured_limit = context.settings.defaults.max_tool_loop_iterations
    limit = 1 if configured_limit is None else configured_limit

    next_value = int(context.metadata.get("tool_loop_iterations", 0)) + 1
    if next_value > limit:
        raise OrchestrationLimitExceededError(
            f"The tool-assisted strategy exceeded the max tool loop iteration limit ({limit})."
        )
    context.metadata["tool_loop_iterations"] = next_value
    return next_value


def _tool_result_section(tool_result: ToolExecutionResult) -> PromptSection:
    return PromptSection(
        title="Tool result",
        body=(
            f"Tool `{tool_result.tool_name}` returned status `{tool_result.status}`.\n"
            f"Summary: {tool_result_safe_text(tool_result)}"
        ),
    )


def _supports_direct_tool_summary(tool_result: ToolExecutionResult) -> bool:
    return tool_result.tool_name == "websearch.search"


def _build_direct_tool_summary_result(
    *,
    agent_name: str,
    llm_profile: str | None,
    tool_result: ToolExecutionResult,
):
    return build_run_result(
        status="completed",
        answer=_format_direct_tool_answer(tool_result),
        agent_name=agent_name,
        llm_profile=llm_profile,
        metadata={"response_mode": "final_answer", "tool_summary_fallback": True},
    )


def _format_direct_tool_answer(tool_result: ToolExecutionResult) -> str:
    structured = tool_result.structured_content or {}
    if structured.get("ok") is not True:
        error = structured.get("error")
        if isinstance(error, dict):
            message = _read_optional_str(error.get("message"))
            if message is not None:
                return message
        return tool_result_safe_text(tool_result)

    results = structured.get("results")
    if not isinstance(results, Sequence) or isinstance(results, str | bytes | bytearray) or not results:
        return "The web search tool returned no results."

    lines = ["Here are the top web results:"]
    for item in list(results)[:3]:
        if not isinstance(item, dict):
            continue
        title = _read_optional_str(item.get("title")) or "Untitled result"
        snippet = _read_optional_str(item.get("snippet"))
        url = _read_optional_str(item.get("url"))
        line = f"- {title}"
        if snippet:
            line += f": {snippet}"
        if url:
            line += f" ({url})"
        lines.append(line)

    if len(lines) == 1:
        return "The web search tool returned no readable results."
    return "\n".join(lines)


def _read_finish_reason(metadata: dict[str, Any]) -> str:
    finish_reason = _read_optional_str(metadata.get("finish_reason"))
    return finish_reason or "completed"


def _cancellation_token(context: OrchestrationContext) -> object | None:
    if context.runtime is None:
        return None
    return context.runtime.cancellation_token