"""In-memory fake agent for contract-focused tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from app.agents.base import LegacyCompatibleAgent
from app.agents.models import AgentCapabilities, AgentRunRequest, AgentRunResult, AgentStreamEvent, AgentUsageSummary
from app.agents.result_builder import build_run_result
from app.agents.stream_mapping import build_completed_event, build_started_event, map_llm_stream_event
from app.contracts.context import OrchestrationContext
from app.contracts.llm import LLMMessage, LLMRequest
from app.contracts.memory import MemoryScope, MemorySearchRequest
from app.orchestration.memory_intents import MemoryCandidate, build_memory_candidates
from app.orchestration.tool_intents import ToolIntent


_TOOL_TRIGGER_PREFIX = "tool:"
_DEFAULT_TOOL_LIMIT = 3


class FakeAgent(LegacyCompatibleAgent):
    """Deterministic agent that delegates generation to the LLM gateway."""

    name = "fake_agent"
    type = "custom"
    description = "A fake test agent."
    capabilities = ["test"]
    structured_capabilities = AgentCapabilities(
        answer=True,
        stream=True,
        memory_read=True,
        tool_execute=True,
        self_managed_memory=True,
        self_managed_tools=True,
    )

    def __init__(self, name: str | None = None, component: str | None = None) -> None:
        if name is not None:
            self.name = name
        self.component = component or f"agent.{self.name}"
        self.runs: list[OrchestrationContext] = []

    async def run_structured(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> AgentRunResult:
        self.runs.append(context)
        metadata: dict[str, object] = {}
        memory_search_count = await self._memory_search_count(request=request, context=context)
        if memory_search_count is not None:
            metadata["memory_result_count"] = memory_search_count

        memory_candidates = self._maybe_extract_memory_candidates(request=request, context=context)
        if memory_candidates is not None:
            return build_run_result(
                status="completed",
                answer=None,
                agent_name=self.name,
                memory_candidates=tuple(memory_candidates),
                usage=AgentUsageSummary(
                    llm_calls=0,
                    memory_searches=0 if memory_search_count is None else 1,
                    input_chars=len(request.message),
                    output_chars=0,
                ),
                metadata={
                    **metadata,
                    "candidate_count": len(memory_candidates),
                },
            )

        tool_intent = self._maybe_prepare_tool_intent(request=request, context=context)
        if tool_intent is not None:
            return self._tool_intent_run_result(
                request=request,
                tool_intent=tool_intent,
                metadata=metadata,
                memory_search_count=0 if memory_search_count is None else 1,
            )

        response = await context.llm.complete(
            LLMRequest(
                component=self.component,
                messages=[LLMMessage(role="user", content=self._request_message_content(request))],
                profile=request.llm_profile,
            ),
            context,
        )
        if response.finish_reason:
            metadata["finish_reason"] = response.finish_reason
        return build_run_result(
            status="completed",
            answer=response.text,
            agent_name=self.name,
            llm_profile=response.profile,
            usage=AgentUsageSummary(
                llm_calls=1,
                memory_searches=0 if memory_search_count is None else 1,
                input_chars=len(request.message),
                output_chars=len(response.text),
            ),
            metadata=metadata,
        )

    async def stream(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[AgentStreamEvent]:
        self.runs.append(context)
        yield build_started_event(
            self.name,
            metadata={"agent_type": self.type, "llm_profile": request.llm_profile},
        )

        memory_search_count = await self._memory_search_count(request=request, context=context)
        memory_candidates = self._maybe_extract_memory_candidates(request=request, context=context)
        if memory_candidates is not None:
            yield build_completed_event(
                self.name,
                result=build_run_result(
                    status="completed",
                    answer=None,
                    agent_name=self.name,
                    memory_candidates=tuple(memory_candidates),
                    usage=AgentUsageSummary(
                        llm_calls=0,
                        memory_searches=0 if memory_search_count is None else 1,
                        input_chars=len(request.message),
                        output_chars=0,
                    ),
                    metadata={"candidate_count": len(memory_candidates)},
                ),
            )
            return

        tool_intent = self._maybe_prepare_tool_intent(request=request, context=context)
        if tool_intent is not None:
            result = self._tool_intent_run_result(
                request=request,
                tool_intent=tool_intent,
                metadata={},
                memory_search_count=0 if memory_search_count is None else 1,
            )
            yield build_completed_event(self.name, result=result)
            return

        answer_parts: list[str] = []
        finish_reason: str | None = None
        llm_profile = request.llm_profile
        async for raw_event in context.llm.stream(
            LLMRequest(
                component=self.component,
                messages=[LLMMessage(role="user", content=self._request_message_content(request))],
                profile=request.llm_profile,
                stream=True,
            ),
            context,
        ):
            mapped = map_llm_stream_event(self.name, raw_event)
            if mapped is not None:
                yield mapped
            if raw_event.text:
                answer_parts.append(raw_event.text)
            if raw_event.profile:
                llm_profile = raw_event.profile
            if raw_event.finish_reason:
                finish_reason = raw_event.finish_reason

        metadata: dict[str, object] = {}
        if finish_reason is not None:
            metadata["finish_reason"] = finish_reason
        if memory_search_count is not None:
            metadata["memory_result_count"] = memory_search_count

        yield build_completed_event(
            self.name,
            result=build_run_result(
                status="completed",
                answer="".join(answer_parts),
                agent_name=self.name,
                llm_profile=llm_profile,
                usage=AgentUsageSummary(
                    llm_calls=1,
                    memory_searches=0 if memory_search_count is None else 1,
                    input_chars=len(request.message),
                    output_chars=len("".join(answer_parts)),
                ),
                metadata=metadata,
            ),
        )

    def _memory_search_enabled(self, context: OrchestrationContext) -> bool:
        configured = context.config.get(f"agents.{self.name}.memory.search_enabled", False)
        if not isinstance(configured, bool) or not configured:
            return False

        memory_enabled = context.config.get("memory.enabled")
        if isinstance(memory_enabled, bool):
            return memory_enabled
        return bool(context.config.get("features.memory_enabled", False))

    async def _memory_search_count(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> int | None:
        if not self._memory_search_enabled(context):
            return None
        result = await context.memory.search(
            MemorySearchRequest(text=request.message, scope=MemoryScope()),
            context,
        )
        return len(result.results)

    async def _maybe_execute_tool(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> ToolIntent | None:
        return self._maybe_prepare_tool_intent(request=request, context=context)

    def _maybe_prepare_tool_intent(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> ToolIntent | None:
        if request.tool_context:
            return None
        query = self._requested_tool_query(request.message)
        if query is None:
            return None

        tool_name = self._configured_tool_name(request=request, context=context)
        if tool_name is None:
            return None

        return ToolIntent(
            tool_name=tool_name,
            arguments=_tool_arguments(tool_name, query),
            query=query,
            metadata={
                "status": "planned",
                "reason": "Fake agent requested one logical tool intent.",
            },
        )

    def _maybe_extract_memory_candidates(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> tuple[MemoryCandidate, ...] | None:
        output_kind = None if request.output_format is None else request.output_format.kind
        if output_kind != "memory_candidates" and request.strategy_name != "memory_update":
            return None
        candidate_limit = 1
        if request.output_format is not None and isinstance(request.output_format.max_items, int):
            candidate_limit = max(1, request.output_format.max_items)
        return tuple(build_memory_candidates(context, candidate_limit=candidate_limit))

    def _tool_intent_run_result(
        self,
        *,
        request: AgentRunRequest,
        tool_intent: ToolIntent,
        metadata: dict[str, object],
        memory_search_count: int,
    ) -> AgentRunResult:
        return build_run_result(
            status="completed",
            answer=None,
            agent_name=self.name,
            tool_intents=(tool_intent,),
            usage=AgentUsageSummary(
                tool_calls=0,
                memory_searches=memory_search_count,
                input_chars=len(request.message),
                output_chars=0,
            ),
            metadata=metadata,
        )

    def _request_message_content(self, request: AgentRunRequest) -> str:
        sections: list[str] = []
        if request.session_summary:
            sections.append(f"Session summary:\n{request.session_summary}")
        for section in (*request.context_items, *request.tool_context):
            sections.append(section.render())
        if request.constraints:
            sections.append("Constraints:\n" + "\n".join(f"- {item}" for item in request.constraints))
        if not sections:
            return request.message
        sections.append(f"User request:\n{request.message}")
        return "\n\n".join(sections)

    def _requested_tool_query(self, message: str) -> str | None:
        normalized = message.strip()
        if not normalized.lower().startswith(_TOOL_TRIGGER_PREFIX):
            return None

        query = normalized[len(_TOOL_TRIGGER_PREFIX) :].strip()
        return query or normalized

    def _configured_tool_name(
        self,
        *,
        request: AgentRunRequest,
        context: OrchestrationContext,
    ) -> str | None:
        if request.available_tools:
            return request.available_tools[0]

        agent_tools = _read_string_list(context.config.get(f"agents.{self.name}.allowed_tools"))
        if agent_tools:
            return agent_tools[0]

        usecase_name = context.request.usecase
        if usecase_name is None:
            return None

        tools_enabled = context.config.get(f"usecases.{usecase_name}.tools.enabled", False)
        if isinstance(tools_enabled, bool) and not tools_enabled:
            return None

        usecase_tools = _read_string_list(
            context.config.get(f"usecases.{usecase_name}.tools.allowed_tools")
        )
        if not usecase_tools:
            return None
        return usecase_tools[0]


def _tool_arguments(tool_name: str, query: str) -> dict[str, object]:
    if "search" in tool_name:
        return {"query": query, "limit": _DEFAULT_TOOL_LIMIT}
    return {"text": query}


def _read_string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []

    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text:
            normalized.append(text)
    return normalized