"""Direct-agent orchestration strategy."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any, cast

from app.contracts.agents import AgentHandle, AgentPlugin, build_run_request_from_context
from app.contracts.config import ConfigurationView
from app.contracts.context import OrchestrationContext
from app.contracts.errors import ConfigurationError
from app.contracts.llm import (
    LLMGateway,
    LLMHealthResult,
    LLMProfileSummary,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
)
from app.contracts.memory import (
    DocumentIngestRequest,
    DocumentIngestResult,
    MemoryChunkContextRequest,
    MemoryChunkContextResult,
    MemoryContradictRequest,
    MemoryDeleteByScopeRequest,
    MemoryDeleteResult,
    MemoryExportByScopeRequest,
    MemoryExportResult,
    MemoryForgetRequest,
    MemoryGetRequest,
    MemoryHealthResult,
    MemoryLifecycleRequest,
    MemoryRecord,
    MemoryScope,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryStatsResult,
    MemorySupersedeRequest,
    MemoryWrite,
    MemoryWriteResult,
)
from app.contracts.policy import PolicyRequest
from app.contracts.results import OrchestrationResult as LegacyOrchestrationResult
from app.contracts.results import StreamEvent
from app.contracts.tools import (
    ToolCallRequest,
    ToolCapabilitiesResult,
    ToolErrorDetail,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolHealthResult,
    ToolListFilters,
    ToolListResult,
    ToolResultSummary,
    ToolScopes,
    ToolSpec,
    ToolStreamEvent,
)
from app.orchestration.errors import AgentExecutionError, AgentNotFoundError, OrchestrationCancelledError
from app.orchestration.events import OrchestrationStreamEvent
from app.orchestration.models import sanitize_metadata
from app.orchestration.registry import agent_component
from app.orchestration.strategy_steps import (
    agent_result_answer,
    build_agent_result_metadata,
    build_citation_summaries_from_agent_result,
    build_memory_update_summaries_from_agent_result,
    build_step_summary,
    build_tool_call_summaries_from_agent_result,
    finalize_strategy_result,
    run_agent_step,
)


_DIRECT_AGENT_COMPONENT = "orchestration.strategy.direct_agent"
_PROFILE_OVERRIDE_KEYS = ("llm_profile_override", "requested_llm_profile")


@dataclass(slots=True)
class DirectAgentStrategy:
    """Strategy that runs one configured agent through the provider-neutral gateway stack."""

    name: str = "direct_agent"

    async def run(
        self,
        *,
        context: OrchestrationContext,
        agents: Sequence[AgentPlugin],
    ) -> LegacyOrchestrationResult:
        started_at = perf_counter()
        agent = _require_agent(context, agents)
        agent_name = _runtime_value(context, "agent_name") or agent.name
        execution_context = await _build_execution_context(context, agent_name=agent_name)
        strategy_name = _runtime_value(context, "strategy_name") or self.name

        result = await run_agent_step(
            execution_context,
            component=_DIRECT_AGENT_COMPONENT,
            agent=agent,
            strategy_name=strategy_name,
        )
        resolved_agent_name = result.agent_name or agent_name
        llm_profile = (
            result.llm_profile
            or _runtime_value(execution_context, "llm_profile")
            or _read_optional_str(context.config.get(f"agents.{agent_name}.llm_profile"))
            or _read_optional_str(context.config.get("llm.defaults.profile"))
        )

        metadata = _build_safe_result_metadata(
            build_agent_result_metadata(result),
            agent_name=agent_name,
            agent=agent,
            llm_profile=llm_profile,
            tool_call_count=len(result.tool_intents),
            memory_update_count=len(result.memory_candidates),
        )
        duration_ms = int((perf_counter() - started_at) * 1000)

        strategy_result = finalize_strategy_result(
            answer=agent_result_answer(result),
            agent_name=resolved_agent_name,
            llm_profile=llm_profile,
            finish_reason=_read_finish_reason(metadata),
            steps=[
                build_step_summary(
                    step_id=f"{strategy_name}:agent",
                    step_type="agent",
                    status="completed",
                    duration_ms=duration_ms,
                    safe_message="Direct agent response completed.",
                    metadata={
                        "agent_name": resolved_agent_name,
                        "llm_profile": llm_profile,
                        "tool_call_count": len(result.tool_intents),
                        "memory_update_count": len(result.memory_candidates),
                    },
                )
            ],
            tool_calls=build_tool_call_summaries_from_agent_result(result),
            memory_updates=build_memory_update_summaries_from_agent_result(result),
            citations=build_citation_summaries_from_agent_result(result),
            metadata={**metadata, "duration_ms": duration_ms},
        )
        return strategy_result.to_legacy_result(
            session_id=context.request.session_id,
            trace_id=context.request.trace_id or "unknown_trace",
            strategy_name=strategy_name,
        )

    async def stream(
        self,
        *,
        context: OrchestrationContext,
        agents: Sequence[AgentPlugin],
    ) -> AsyncIterator[StreamEvent | OrchestrationStreamEvent]:
        agent = _require_agent(context, agents)
        agent_name = _runtime_value(context, "agent_name") or agent.name
        execution_context = await _build_execution_context(context, agent_name=agent_name)
        strategy_name = _runtime_value(context, "strategy_name") or self.name
        request = build_run_request_from_context(
            execution_context,
            agent_name=agent.name,
            strategy_name=strategy_name,
        )

        emitted_answer = False
        async for event in cast(AgentHandle, agent).stream(request=request, context=execution_context):
            if event.type == "agent.llm.delta" and event.text:
                emitted_answer = True
                yield OrchestrationStreamEvent.response_delta(
                    trace_id=context.request.trace_id or "unknown_trace",
                    session_id=context.request.session_id,
                    text=event.text,
                )
                continue

            if event.type == "agent.completed" and event.result is not None:
                result = event.result
                resolved_agent_name = result.agent_name or agent_name
                llm_profile = (
                    result.llm_profile
                    or _runtime_value(execution_context, "llm_profile")
                    or _read_optional_str(context.config.get(f"agents.{agent_name}.llm_profile"))
                    or _read_optional_str(context.config.get("llm.defaults.profile"))
                )
                metadata = _build_safe_result_metadata(
                    build_agent_result_metadata(result),
                    agent_name=agent_name,
                    agent=agent,
                    llm_profile=llm_profile,
                    tool_call_count=len(result.tool_intents),
                    memory_update_count=len(result.memory_candidates),
                )
                answer = agent_result_answer(result)
                if answer and not emitted_answer:
                    yield OrchestrationStreamEvent.response_delta(
                        trace_id=context.request.trace_id or "unknown_trace",
                        session_id=context.request.session_id,
                        text=answer,
                    )

                for tool_call in build_tool_call_summaries_from_agent_result(result):
                    yield StreamEvent(event_type="tool_call_summary", data=tool_call.as_legacy_dict())

                agent_summary = {
                    "agent_name": resolved_agent_name,
                    "strategy_name": strategy_name,
                    "llm_profile": llm_profile,
                }
                for key, value in metadata.items():
                    if key == "finish_reason":
                        continue
                    agent_summary[key] = value
                yield StreamEvent(event_type="agent_summary", data=agent_summary)
                yield OrchestrationStreamEvent.response_completed(
                    trace_id=context.request.trace_id or "unknown_trace",
                    session_id=context.request.session_id,
                    finish_reason=_read_finish_reason(metadata),
                )
                return

            if event.type == "agent.failed":
                raise AgentExecutionError(
                    "Streaming agent execution failed."
                    if event.error is None or not event.error.message
                    else event.error.message
                )

            if event.type == "agent.cancelled":
                raise OrchestrationCancelledError()


async def _build_execution_context(
    context: OrchestrationContext,
    *,
    agent_name: str,
) -> OrchestrationContext:
    llm_profile = await _resolve_llm_profile(context, agent_name=agent_name)
    memory_enabled = _memory_enabled(context)
    tools_enabled = _tools_enabled(context)
    usecase_name = _read_optional_str(context.request.usecase)

    overrides: dict[str, object] = {}
    if not memory_enabled:
        overrides["memory.enabled"] = False
        overrides["features.memory_enabled"] = False
        overrides[f"agents.{agent_name}.memory.search_enabled"] = False
    if not tools_enabled:
        overrides[f"agents.{agent_name}.allowed_tools"] = ()
        if usecase_name is not None:
            overrides[f"usecases.{usecase_name}.tools.enabled"] = False
            overrides[f"usecases.{usecase_name}.tools.allowed_tools"] = ()
            overrides[f"orchestration.usecases.{usecase_name}.tools.enabled"] = False
            overrides[f"orchestration.usecases.{usecase_name}.tools.allowed_tools"] = ()

    runtime_metadata = dict(context.runtime_metadata)
    if llm_profile is not None:
        runtime_metadata["llm_profile"] = llm_profile
    runtime_metadata["memory_enabled"] = memory_enabled
    runtime_metadata["tools_enabled"] = tools_enabled

    return replace(
        context,
        llm=_ProfileSelectingLLMGateway(context.llm, default_profile=llm_profile),
        memory=context.memory if memory_enabled else _DisabledMemoryGateway(),
        tools=context.tools if tools_enabled else _DisabledToolGateway(),
        config=_FeatureGatedConfigurationView(context.config, overrides=overrides),
        runtime_metadata=runtime_metadata,
    )


async def _resolve_llm_profile(
    context: OrchestrationContext,
    *,
    agent_name: str,
) -> str | None:
    override = _request_profile_override(context)
    if override is not None and await _profile_override_allowed(context, override, agent_name=agent_name):
        return override

    usecase_profile = None
    usecase_name = _read_optional_str(context.request.usecase)
    if context.settings is not None and usecase_name is not None:
        usecase = context.settings.usecases.get(usecase_name)
        if usecase is not None:
            usecase_profile = usecase.llm_profile

    strategy_profile = None if context.strategy_settings is None else context.strategy_settings.llm_profile
    agent_profile = _read_optional_str(context.config.get(f"agents.{agent_name}.llm_profile"))
    routed_profile = _runtime_value(context, "llm_profile")
    default_profile = _read_optional_str(context.config.get("llm.defaults.profile"))
    return usecase_profile or strategy_profile or agent_profile or routed_profile or default_profile


async def _profile_override_allowed(
    context: OrchestrationContext,
    llm_profile: str,
    *,
    agent_name: str,
) -> bool:
    decision = await context.policy.evaluate(
        PolicyRequest(
            action="llm.complete",
            component=_DIRECT_AGENT_COMPONENT,
            resource=llm_profile,
            scope={
                "usecase_name": context.request.usecase,
                "strategy_name": _runtime_value(context, "strategy_name") or "direct_agent",
                "agent_name": agent_name,
            },
            metadata={"override_source": "request_metadata"},
        ),
        context,
    )
    return decision.allowed


def _memory_enabled(context: OrchestrationContext) -> bool:
    if context.strategy_settings is None or not context.strategy_settings.memory_enabled:
        return False
    usecase = _resolve_usecase_settings(context)
    if usecase is None:
        return True
    return bool(usecase.memory.enabled)


def _tools_enabled(context: OrchestrationContext) -> bool:
    if context.strategy_settings is None or not context.strategy_settings.tools_enabled:
        return False
    usecase = _resolve_usecase_settings(context)
    if usecase is None:
        return True
    return bool(usecase.tools.enabled)


def _resolve_usecase_settings(context: OrchestrationContext) -> Any | None:
    if context.settings is None:
        return None
    usecase_name = _read_optional_str(context.request.usecase)
    if usecase_name is None:
        return None
    return context.settings.usecases.get(usecase_name)


def _request_profile_override(context: OrchestrationContext) -> str | None:
    for key in _PROFILE_OVERRIDE_KEYS:
        value = _read_optional_str(context.request.metadata.get(key))
        if value is not None:
            return value
    return None


def _build_safe_result_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    agent_name: str,
    agent: AgentPlugin,
    llm_profile: str | None,
    tool_call_count: int,
    memory_update_count: int,
) -> dict[str, Any]:
    safe_metadata = sanitize_metadata(metadata)
    safe_metadata.setdefault("finish_reason", _read_optional_str(safe_metadata.get("finish_reason")) or "stop")
    safe_metadata.setdefault("agent_component", agent_component(agent, agent_name))
    if llm_profile is not None:
        safe_metadata.setdefault("llm_profile", llm_profile)
    safe_metadata.setdefault("tool_call_count", tool_call_count)
    safe_metadata.setdefault("memory_update_count", memory_update_count)
    return safe_metadata


def _require_agent(
    context: OrchestrationContext,
    agents: Sequence[AgentPlugin],
) -> AgentPlugin:
    if not agents:
        raise AgentNotFoundError("No agent is configured for the selected strategy.")
    preferred_name = _runtime_value(context, "agent_name")
    if preferred_name is not None:
        for agent in agents:
            if agent.name == preferred_name:
                return agent
    return agents[0]


def _runtime_value(context: OrchestrationContext, key: str) -> str | None:
    value = context.runtime_metadata.get(key)
    return _read_optional_str(value)


def _read_finish_reason(metadata: Mapping[str, Any]) -> str:
    finish_reason = _read_optional_str(metadata.get("finish_reason"))
    return finish_reason or "stop"


def _read_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


class _FeatureGatedConfigurationView:
    def __init__(self, base: ConfigurationView, *, overrides: Mapping[str, object]) -> None:
        self._base = base
        self._overrides = dict(overrides)

    def get(self, path: str, default: Any = None) -> Any:
        if path in self._overrides:
            return self._overrides[path]
        return self._base.get(path, default)

    def require(self, path: str) -> Any:
        if path in self._overrides:
            value = self._overrides[path]
            if value is None:
                raise ConfigurationError(f"Missing required config path: {path}")
            return value
        return self._base.require(path)

    def section(self, path: str) -> dict[str, Any]:
        if path in self._overrides:
            value = self._overrides[path]
            if not isinstance(value, Mapping):
                raise ConfigurationError(f"Config path is not a section: {path}")
            return dict(value)
        return self._base.section(path)


class _ProfileSelectingLLMGateway:
    def __init__(self, gateway: LLMGateway, *, default_profile: str | None) -> None:
        self._gateway = gateway
        self._default_profile = default_profile

    async def complete(self, request: LLMRequest, context: OrchestrationContext) -> LLMResponse:
        return await self._gateway.complete(self._resolve_request(request), context)

    async def stream(
        self,
        request: LLMRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[LLMStreamEvent]:
        async for event in self._gateway.stream(self._resolve_request(request), context):
            yield event

    async def health(self) -> LLMHealthResult:
        return await self._gateway.health()

    async def list_profiles(self) -> list[LLMProfileSummary]:
        return await self._gateway.list_profiles()

    def _resolve_request(self, request: LLMRequest) -> LLMRequest:
        if request.profile is not None or self._default_profile is None:
            return request
        return replace(request, profile=self._default_profile)


class _DisabledMemoryGateway:
    async def search(
        self,
        request: MemorySearchRequest,
        context: OrchestrationContext,
    ) -> MemorySearchResult:
        _ = context
        return MemorySearchResult(results=[], query_id=request.query_id, metadata={"disabled": True})

    async def get(
        self,
        request: MemoryGetRequest,
        context: OrchestrationContext,
    ) -> MemoryRecord | None:
        _ = request
        _ = context
        return None

    async def get_chunk_context(
        self,
        request: MemoryChunkContextRequest,
        context: OrchestrationContext,
    ) -> MemoryChunkContextResult | None:
        _ = request
        _ = context
        return None

    async def upsert(
        self,
        memory: MemoryWrite,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        _ = context
        return MemoryWriteResult(
            operation="upsert",
            status="disabled",
            changed=False,
            metadata={"disabled": True, "memory_type": memory.memory_type},
        )

    async def promote(
        self,
        request: MemoryLifecycleRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        return await self._disabled_lifecycle_result("promote", request, context)

    async def supersede(
        self,
        request: MemorySupersedeRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        _ = context
        return MemoryWriteResult(
            operation="supersede",
            status="disabled",
            changed=False,
            affected_ids=(request.old_memory_id, request.new_memory_id),
            metadata={"disabled": True},
        )

    async def contradict(
        self,
        request: MemoryContradictRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        _ = context
        return MemoryWriteResult(
            operation="contradict",
            status="disabled",
            changed=False,
            affected_ids=(request.memory_id_a, request.memory_id_b),
            metadata={"disabled": True},
        )

    async def expire(
        self,
        request: MemoryLifecycleRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        return await self._disabled_lifecycle_result("expire", request, context)

    async def forget(
        self,
        request: MemoryForgetRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        _ = context
        return MemoryWriteResult(
            operation="forget",
            status="disabled",
            changed=False,
            affected_ids=(request.memory_id,),
            metadata={"disabled": True},
        )

    async def ingest_document(
        self,
        request: DocumentIngestRequest,
        context: OrchestrationContext,
    ) -> DocumentIngestResult:
        _ = context
        return DocumentIngestResult(
            source_id=request.source_id,
            document_id=request.document_id,
            source_hash=request.source_hash,
            status="disabled",
            metadata={"disabled": True},
        )

    async def delete_by_scope(
        self,
        request: MemoryDeleteByScopeRequest,
        context: OrchestrationContext,
    ) -> MemoryDeleteResult:
        _ = context
        return MemoryDeleteResult(
            scope=request.scope,
            deleted_count=0,
            hard_delete=request.hard_delete,
            metadata={"disabled": True},
        )

    async def export_by_scope(
        self,
        request: MemoryExportByScopeRequest,
        context: OrchestrationContext,
    ) -> MemoryExportResult:
        _ = context
        return MemoryExportResult(scope=request.scope, records=[], metadata={"disabled": True})

    async def health(self) -> MemoryHealthResult:
        return MemoryHealthResult(
            status="disabled",
            enabled=False,
            provider="disabled",
            configured=False,
            search_available=False,
            ingest_available=False,
            metadata={"disabled": True},
        )

    async def stats(
        self,
        scopes: MemoryScope | None = None,
        context: OrchestrationContext | None = None,
    ) -> MemoryStatsResult:
        _ = scopes
        _ = context
        return MemoryStatsResult(total_records=0, status="disabled", configured=False, metadata={"disabled": True})

    async def _disabled_lifecycle_result(
        self,
        operation: str,
        request: MemoryLifecycleRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        _ = context
        return MemoryWriteResult(
            operation=operation,
            status="disabled",
            changed=False,
            affected_ids=(request.memory_id,),
            metadata={"disabled": True},
        )


class _DisabledToolGateway:
    async def list_tools(
        self,
        context: OrchestrationContext,
        filters: ToolListFilters | None = None,
    ) -> ToolListResult:
        _ = context
        _ = filters
        return ToolListResult(tools=[])

    async def get_tool(
        self,
        tool_name: str,
        context: OrchestrationContext,
    ) -> ToolSpec | None:
        _ = tool_name
        _ = context
        return None

    async def execute(
        self,
        request: ToolExecutionRequest,
        context: OrchestrationContext,
    ) -> ToolExecutionResult:
        _ = context
        return ToolExecutionResult(
            tool_name=request.tool_name,
            status="failed",
            summary=ToolResultSummary(safe_message="Tool execution is not enabled for direct_agent."),
            error_detail=ToolErrorDetail(
                code="tool_disabled",
                message="Tool execution is not enabled for direct_agent.",
            ),
            metadata={"disabled": True},
        )

    async def stream_execute(
        self,
        request: ToolExecutionRequest,
        context: OrchestrationContext,
    ) -> AsyncIterator[ToolStreamEvent]:
        _ = context
        yield ToolStreamEvent.error_event(
            tool_name=request.tool_name,
            error=ToolErrorDetail(
                code="tool_disabled",
                message="Tool execution is not enabled for direct_agent.",
            ),
            metadata={"disabled": True},
        )

    async def health(self) -> ToolHealthResult:
        return ToolHealthResult(
            status="disabled",
            tooling_enabled=False,
            mcp_configured=False,
            mcp_status="not_configured",
            tools_configured=0,
            tools_discovered=0,
            tools_enabled=0,
            registry_status="disabled",
        )

    async def capabilities(self) -> ToolCapabilitiesResult:
        return ToolCapabilitiesResult(
            enabled=False,
            mcp_configured=False,
            streaming_supported=False,
            available_logical_tools=[],
            metadata={"disabled": True},
        )

    async def call_tool(
        self,
        request: ToolCallRequest,
        context: OrchestrationContext,
    ) -> ToolExecutionResult:
        return await self.execute(
            ToolExecutionRequest(
                tool_name=request.tool_name,
                arguments=request.arguments,
                scopes=ToolScopes(),
                stream=request.stream,
                metadata=request.metadata,
            ),
            context,
        )