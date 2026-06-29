"""Base protocols and compatibility helpers for structured agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Protocol, overload

from app.agents.capabilities import memory_required, tools_required, validate_capabilities
from app.agents.errors import normalize_agent_error
from app.agents.models import AgentCapabilities, AgentDescriptor, AgentHealthResult, AgentRunRequest, AgentRunResult, AgentStreamEvent
from app.agents.result_builder import build_run_request_from_context, to_legacy_agent_result
from app.agents.stream_mapping import build_cancelled_event, build_completed_event, build_failed_event, build_started_event
from app.orchestration.models import sanitize_metadata

if TYPE_CHECKING:
    from app.contracts.context import OrchestrationContext
    from app.contracts.results import AgentResult


class AgentHandle(Protocol):
    """Migration-friendly agent protocol supporting legacy and structured calls."""

    name: str
    type: str

    @overload
    async def run(self, context: "OrchestrationContext") -> "AgentResult":
        ...

    @overload
    async def run(
        self,
        *,
        request: AgentRunRequest,
        context: "OrchestrationContext",
    ) -> AgentRunResult:
        ...

    def stream(
        self,
        *,
        request: AgentRunRequest,
        context: "OrchestrationContext",
    ) -> AsyncIterator[AgentStreamEvent]:
        ...

    async def health(self) -> AgentHealthResult:
        ...

    def descriptor(self) -> AgentDescriptor:
        ...


class LegacyCompatibleAgent(ABC):
    """Base class that bridges the structured contract with legacy orchestration."""

    name: str = "agent"
    type = "custom"
    description: str = "Agent"
    enabled = True
    default_llm_profile: str | None = None
    prompt_profile: str | None = None
    display_name: str | None = None
    supported_usecases: tuple[str, ...] = ()
    supported_strategies: tuple[str, ...] = ()
    structured_capabilities = AgentCapabilities(answer=True, stream=True)
    metadata: dict[str, Any] = {}

    @overload
    async def run(self, context: "OrchestrationContext") -> "AgentResult":
        ...

    @overload
    async def run(
        self,
        *,
        request: AgentRunRequest,
        context: "OrchestrationContext",
    ) -> AgentRunResult:
        ...

    async def run(
        self,
        context: "OrchestrationContext | None" = None,
        *,
        request: AgentRunRequest | None = None,
    ) -> AgentRunResult | "AgentResult":
        if context is None:
            raise TypeError("Structured and legacy agent runs require an orchestration context.")

        resolved_request = request or build_run_request_from_context(
            context,
            agent_name=self.name,
            llm_profile=_requested_llm_profile(context, default=self.default_llm_profile),
        )
        result = await self.run_structured(request=resolved_request, context=context)
        if request is None:
            return to_legacy_agent_result(result, fallback_agent_name=self.name)
        return result

    @abstractmethod
    async def run_structured(
        self,
        *,
        request: AgentRunRequest,
        context: "OrchestrationContext",
    ) -> AgentRunResult:
        """Execute the agent using the structured request surface."""

    async def stream(
        self,
        *,
        request: AgentRunRequest,
        context: "OrchestrationContext",
    ) -> AsyncIterator[AgentStreamEvent]:
        yield build_started_event(
            self.name,
            metadata={
                "agent_type": self.type,
                "llm_profile": request.llm_profile or self.default_llm_profile,
            },
        )
        try:
            result = await self.run_structured(request=request, context=context)
        except BaseException as exc:
            normalized = normalize_agent_error(exc)
            if normalized.code == "agent_cancelled":
                yield build_cancelled_event(self.name)
                return
            yield build_failed_event(self.name, error=normalized.to_detail())
            return
        yield build_completed_event(self.name, result=result)

    async def health(self) -> AgentHealthResult:
        descriptor = self.descriptor()
        capabilities = descriptor.capabilities
        return AgentHealthResult(
            agent_name=descriptor.name,
            agent_type=str(descriptor.type),
            status="ok" if descriptor.enabled else "disabled",
            enabled=descriptor.enabled,
            configured_llm_profile=descriptor.llm_profile,
            prompt_profile=self.prompt_profile,
            memory_required=memory_required(capabilities),
            tools_required=tools_required(capabilities),
            streaming_supported=capabilities.stream,
            metadata=sanitize_metadata(self.metadata),
        )

    def descriptor(self) -> AgentDescriptor:
        capabilities = validate_capabilities(self.structured_capabilities)
        return AgentDescriptor(
            name=self.name,
            type=self.type,
            display_name=self.display_name or self.name.replace("_", " ").title(),
            description=self.description,
            enabled=bool(self.enabled),
            llm_profile=self.default_llm_profile,
            capabilities=capabilities,
            supported_usecases=self.supported_usecases,
            supported_strategies=self.supported_strategies,
            metadata=sanitize_metadata(self.metadata),
        )


def _requested_llm_profile(
    context: "OrchestrationContext",
    *,
    default: str | None,
) -> str | None:
    value = context.runtime_metadata.get("llm_profile")
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
    return default


__all__ = ["AgentHandle", "LegacyCompatibleAgent"]