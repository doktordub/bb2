"""Durable memory-update orchestration strategy."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING
from typing import Any

from app.agents.models import AgentOutputFormat
from app.config.view import get_memory_settings
from app.contracts.agents import AgentPlugin
from app.contracts.context import OrchestrationContext
from app.contracts.errors import PolicyDeniedError
from app.contracts.memory import MemoryWrite
from app.contracts.policy import PolicyRequest
from app.contracts.results import OrchestrationResult as LegacyOrchestrationResult
from app.contracts.results import StreamEvent
from app.orchestration.cancellation import raise_if_cancelled
from app.orchestration.errors import AgentNotFoundError
from app.orchestration.events import OrchestrationStreamEvent
from app.orchestration.message_catalog import default_message_template_service
from app.orchestration.memory_intents import MemoryCandidate, build_memory_candidate_scope, build_memory_candidates
from app.orchestration.models import MemoryUpdateSummary

if TYPE_CHECKING:
    from app.orchestration.strategy import StrategyExecutionResult

_COMPONENT = "orchestration.strategy.memory_update"
_NO_CANDIDATE_ANSWER = "I did not find any durable memory to store from that request."
_APPROVAL_REQUIRED_ANSWER = "This memory update requires approval before I can store it."


@dataclass(slots=True)
class MemoryUpdateStrategy:
    """Extract explicit memory candidates and persist them through MemoryGateway only."""

    name: str = "memory_update"

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


async def _run_strategy(
    context: OrchestrationContext,
    *,
    agents: Sequence[AgentPlugin],
) -> StrategyExecutionResult:
    from app.orchestration.strategy_steps import (
        build_agent_result_metadata,
        build_step_summary,
        finalize_strategy_result,
        require_limits,
        run_agent_step,
        run_memory_write_step,
    )

    started_at = perf_counter()
    raise_if_cancelled(_cancellation_token(context))
    strategy_name = _strategy_name(context, default="memory_update")
    strategy_settings = context.strategy_settings
    if strategy_settings is None:
        raise RuntimeError("Strategy settings are required for memory-update execution.")

    limits = require_limits(context, component=_COMPONENT)
    limits.consume_step()
    agent_name = _selected_agent_name(context, agents)

    candidate_limit = _candidate_limit(context)
    write_limit = _write_limit(context)
    agent_metadata: dict[str, Any] = {}
    if isinstance(context.request.metadata.get("memory_candidates"), list):
        candidates = build_memory_candidates(context, candidate_limit=candidate_limit)
    else:
        agent = _selected_agent(context, agents)
        if agent is None:
            raise AgentNotFoundError("No agent is configured for the selected strategy.")
        agent_name = agent.name
        agent_result = await run_agent_step(
            context,
            component=_COMPONENT,
            agent=agent,
            strategy_name=strategy_name,
            output_format=AgentOutputFormat(
                kind="memory_candidates",
                schema_name="memory_candidate_contract",
                require_json=True,
                max_items=candidate_limit,
            ),
            metadata={"candidate_limit": candidate_limit},
        )
        agent_metadata = build_agent_result_metadata(agent_result)
        candidates = list(agent_result.memory_candidates)
    raise_if_cancelled(_cancellation_token(context))

    extraction_step = build_step_summary(
        step_id=f"{strategy_name}:memory_candidate_extraction",
        step_type="memory_candidate_extraction",
        status="completed" if candidates else "skipped",
        safe_message=(
            f"Extracted {len(candidates)} explicit memory candidate(s)."
            if candidates
            else "No durable memory candidates were extracted."
        ),
        metadata={
            "candidate_count": len(candidates),
            "candidate_limit": candidate_limit,
            "write_limit": write_limit,
        },
    )

    if not candidates:
        duration_ms = max(int((perf_counter() - started_at) * 1000), 0)
        return finalize_strategy_result(
            answer=_no_candidate_answer(),
            agent_name=agent_name,
            llm_profile=None,
            finish_reason="no_memory_updates",
            steps=[extraction_step],
            metadata={
                "candidate_count": 0,
                "memory_write_count": 0,
                "approval_required_count": 0,
                "skipped_candidate_count": 0,
                "duration_ms": duration_ms,
                **agent_metadata,
            },
        )

    memory_settings = get_memory_settings(context.config)
    memory_updates: list[MemoryUpdateSummary] = []
    write_count = 0
    approval_required_count = 0
    skipped_candidate_count = max(len(candidates) - write_limit, 0)

    for candidate in candidates[:write_limit]:
        raise_if_cancelled(_cancellation_token(context))
        memory_write = _build_memory_write(
            candidate=candidate,
            context=context,
            agent_name=agent_name,
            strategy_name=strategy_name,
            default_ttl_days=memory_settings.lifecycle.default_ttl_days,
            allow_retrieval_default=memory_settings.privacy.allow_retrieval_default,
            allow_llm_context_default=memory_settings.privacy.allow_llm_context_default,
        )
        decision = await context.policy.evaluate(
            PolicyRequest(
                action="memory.upsert",
                component=_COMPONENT,
                resource=memory_write.memory_type,
                scope={
                    "usecase_name": context.request.usecase,
                    "agent_name": agent_name,
                    "strategy_name": strategy_name,
                },
                metadata={"scope": memory_write.scope.summary()},
            ),
            context,
        )
        if decision.requires_approval:
            approval_required_count += 1
            memory_updates.append(
                MemoryUpdateSummary(
                    operation="upsert",
                    status="approval_required",
                    safe_message=_approval_required_answer(),
                    metadata={
                        "memory_type": memory_write.memory_type,
                        "scope": memory_write.scope.summary(),
                    },
                )
            )
            continue
        if not decision.allowed:
            raise PolicyDeniedError(decision.reason or "Policy denied")

        _, summary = await run_memory_write_step(
            context,
            component=_COMPONENT,
            memory_write=memory_write,
            agent_name=agent_name,
            strategy_name=strategy_name,
        )
        memory_updates.append(summary)
        write_count += 1

    duration_ms = max(int((perf_counter() - started_at) * 1000), 0)
    write_step = build_step_summary(
        step_id=f"{strategy_name}:memory_write",
        step_type="memory_write",
        status=_write_step_status(write_count=write_count, approval_required_count=approval_required_count),
        duration_ms=duration_ms,
        safe_message=_write_step_message(write_count=write_count, approval_required_count=approval_required_count),
        metadata={
            "candidate_count": len(candidates),
            "memory_write_count": write_count,
            "approval_required_count": approval_required_count,
            "skipped_candidate_count": skipped_candidate_count,
        },
    )

    return finalize_strategy_result(
        answer=_answer_text(write_count=write_count, approval_required_count=approval_required_count),
        agent_name=agent_name,
        llm_profile=None,
        finish_reason=_finish_reason(write_count=write_count, approval_required_count=approval_required_count),
        steps=[extraction_step, write_step],
        memory_updates=memory_updates,
        metadata={
            "candidate_count": len(candidates),
            "memory_write_count": write_count,
            "approval_required_count": approval_required_count,
            "skipped_candidate_count": skipped_candidate_count,
            "duration_ms": duration_ms,
            **agent_metadata,
        },
    )


def _build_memory_write(
    *,
    candidate: MemoryCandidate,
    context: OrchestrationContext,
    agent_name: str | None,
    strategy_name: str,
    default_ttl_days: int | None,
    allow_retrieval_default: bool,
    allow_llm_context_default: bool,
) -> MemoryWrite:
    return MemoryWrite(
        text=candidate.text,
        scope=build_memory_candidate_scope(
            context,
            candidate=candidate,
            agent_name=agent_name,
        ),
        memory_type=candidate.memory_type,
        stable_key=candidate.stable_key,
        importance=candidate.importance,
        confidence=candidate.confidence,
        ttl_days=candidate.ttl_days if candidate.ttl_days is not None else default_ttl_days,
        tags=candidate.tags,
        allow_retrieval=(
            candidate.allow_retrieval
            if candidate.allow_retrieval is not None
            else allow_retrieval_default
        ),
        allow_llm_context=(
            candidate.allow_llm_context
            if candidate.allow_llm_context is not None
            else allow_llm_context_default
        ),
        metadata={
            "reason": candidate.reason,
            "strategy_name": strategy_name,
            **dict(candidate.metadata),
        },
    )


def _candidate_limit(context: OrchestrationContext) -> int:
    strategy_settings = context.strategy_settings
    if strategy_settings is None:
        return 1
    if isinstance(strategy_settings.candidate_limit, int) and strategy_settings.candidate_limit > 0:
        return strategy_settings.candidate_limit
    if isinstance(strategy_settings.max_memory_writes, int) and strategy_settings.max_memory_writes > 0:
        return strategy_settings.max_memory_writes
    if context.settings is not None:
        return max(1, context.settings.defaults.max_memory_writes)
    return 1


def _write_limit(context: OrchestrationContext) -> int:
    strategy_settings = context.strategy_settings
    if strategy_settings is not None and isinstance(strategy_settings.max_memory_writes, int):
        if strategy_settings.max_memory_writes > 0:
            return strategy_settings.max_memory_writes
    if context.settings is not None:
        return max(1, context.settings.defaults.max_memory_writes)
    return 1


def _selected_agent_name(
    context: OrchestrationContext,
    agents: Sequence[AgentPlugin],
) -> str | None:
    runtime_agent = _read_optional_text(context.runtime_metadata.get("agent_name"))
    if runtime_agent is not None:
        return runtime_agent
    if context.strategy_settings is not None and context.strategy_settings.default_agent is not None:
        return context.strategy_settings.default_agent
    selected = _selected_agent(context, agents)
    return None if selected is None else selected.name


def _selected_agent(
    context: OrchestrationContext,
    agents: Sequence[AgentPlugin],
) -> AgentPlugin | None:
    runtime_agent = _selected_agent_name(context, agents)
    if runtime_agent is not None:
        for agent in agents:
            if agent.name == runtime_agent:
                return agent
    if agents:
        return agents[0]
    return None


def _strategy_name(context: OrchestrationContext, *, default: str) -> str:
    runtime_value = _read_optional_text(context.runtime_metadata.get("strategy_name"))
    if runtime_value is not None:
        return runtime_value
    return default


def _answer_text(*, write_count: int, approval_required_count: int) -> str:
    if write_count > 0 and approval_required_count > 0:
        return (
            f"I stored {write_count} memory update{'s' if write_count != 1 else ''} "
            f"and left {approval_required_count} pending approval."
        )
    if write_count > 0:
        return f"I stored {write_count} memory update{'s' if write_count != 1 else ''} for future turns."
    if approval_required_count > 0:
        return _approval_required_answer()
    return _no_candidate_answer()


def _finish_reason(*, write_count: int, approval_required_count: int) -> str:
    if write_count > 0:
        return "completed"
    if approval_required_count > 0:
        return "approval_required"
    return "no_memory_updates"


def _write_step_status(*, write_count: int, approval_required_count: int) -> str:
    if write_count > 0:
        return "completed"
    if approval_required_count > 0:
        return "approval_required"
    return "skipped"


def _write_step_message(*, write_count: int, approval_required_count: int) -> str:
    if write_count > 0 and approval_required_count > 0:
        return "Stored approved memory updates and deferred approval-required writes."
    if write_count > 0:
        return "Stored durable memory updates through the memory gateway."
    if approval_required_count > 0:
        return _approval_required_answer()
    return "No durable memory updates were written."


def _no_candidate_answer() -> str:
    return default_message_template_service().get_text(
        "memory_update",
        "no_candidate_answer",
        fallback=_NO_CANDIDATE_ANSWER,
    )


def _approval_required_answer() -> str:
    return default_message_template_service().get_text(
        "memory_update",
        "approval_required_answer",
        fallback=_APPROVAL_REQUIRED_ANSWER,
    )


def _stream_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if key in {
            "candidate_count",
            "memory_write_count",
            "approval_required_count",
            "skipped_candidate_count",
        }
    }


def _read_finish_reason(metadata: dict[str, Any]) -> str:
    finish_reason = _read_optional_text(metadata.get("finish_reason"))
    return finish_reason or "completed"


def _cancellation_token(context: OrchestrationContext) -> object | None:
    runtime = context.runtime
    if runtime is None:
        return None
    return runtime.cancellation_token


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None