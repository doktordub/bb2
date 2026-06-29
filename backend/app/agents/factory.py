"""Factory helpers for building configured agent handles during startup."""

from __future__ import annotations

from importlib import import_module
from inspect import isawaitable
from typing import Any, cast

from app.agents.base import LegacyCompatibleAgent
from app.agents.capabilities import capabilities_from_settings, capability_labels
from app.agents.models import AgentRunResult
from app.agents.result_builder import build_run_result, from_legacy_agent_result
from app.config.view import AgentPluginSettings, AgentsSettings
from app.contracts.errors import ConfigurationError
from app.contracts.results import AgentResult

_BUILTIN_AGENT_ENTRYPOINTS: dict[str, tuple[str, str]] = {
    "general_assistant": (
        "app.agents.plugins.general_assistant",
        "GeneralAssistantAgent",
    ),
    "document_qa": (
        "app.agents.plugins.document_qa",
        "DocumentQaAgent",
    ),
    "tool_using": (
        "app.agents.plugins.tool_using",
        "ToolUsingAgent",
    ),
    "project_agent": (
        "app.agents.plugins.project_agent",
        "ProjectAgent",
    ),
    "memory_curator": (
        "app.agents.plugins.memory_curator",
        "MemoryCuratorAgent",
    ),
    "reviewer": (
        "app.agents.plugins.reviewer",
        "ReviewerAgent",
    ),
}


class AgentFactory:
    """Build configured agent instances without importing provider SDKs."""

    def __init__(self, *, settings: AgentsSettings) -> None:
        self._settings = settings

    def build(self, agent_settings: AgentPluginSettings) -> object:
        if not agent_settings.enabled:
            raise ConfigurationError(
                f"Disabled agent '{agent_settings.name}' cannot be built."
            )

        agent_class = _resolve_agent_class(agent_settings)
        instance = _instantiate_agent(agent_class, agent_settings.name)
        _apply_agent_settings(instance, agent_settings)

        if isinstance(instance, LegacyCompatibleAgent):
            return instance
        if _supports_structured_contract(instance):
            return instance
        if not callable(getattr(instance, "run", None)):
            raise ConfigurationError(
                f"Configured agent '{agent_settings.name}' does not implement run(...)."
            )
        return _LegacyAgentAdapter(instance, agent_settings)


class _LegacyAgentAdapter(LegacyCompatibleAgent):
    """Structured compatibility wrapper for legacy run(context) agents."""

    def __init__(self, delegate: object, settings: AgentPluginSettings) -> None:
        self._delegate = delegate
        _apply_agent_settings(self, settings)

    async def run_structured(
        self,
        *,
        request: object,
        context: object,
    ) -> AgentRunResult:
        raw_result = cast(Any, self._delegate).run(context)
        if isawaitable(raw_result):
            raw_result = await raw_result
        if isinstance(raw_result, AgentRunResult):
            return _normalize_result(
                raw_result,
                agent_name=self.name,
                llm_profile=self.default_llm_profile,
            )
        if not isinstance(raw_result, AgentResult):
            raise ConfigurationError(
                f"Configured agent '{self.name}' returned an unsupported result type."
            )
        return _normalize_result(
            from_legacy_agent_result(raw_result),
            agent_name=self.name,
            llm_profile=self.default_llm_profile,
        )


def _resolve_agent_class(agent_settings: AgentPluginSettings) -> object:
    module_name: str | None = None
    class_name: str | None = None

    if agent_settings.module is not None or agent_settings.class_name is not None:
        module_name = agent_settings.module
        class_name = agent_settings.class_name
    else:
        builtin = _BUILTIN_AGENT_ENTRYPOINTS.get(agent_settings.type)
        if builtin is not None:
            module_name, class_name = builtin

    if module_name is None or class_name is None:
        if agent_settings.type == "custom":
            raise ConfigurationError(
                f"Custom agent '{agent_settings.name}' requires module and class_name."
            )
        raise ConfigurationError(
            f"Built-in agent type '{agent_settings.type}' is not implemented yet for "
            f"agent '{agent_settings.name}'."
        )

    try:
        module = import_module(module_name)
    except ImportError as exc:
        raise ConfigurationError(
            f"Unable to import agent module '{module_name}'."
        ) from exc

    agent_class = getattr(module, class_name, None)
    if agent_class is None:
        raise ConfigurationError(
            f"Agent class '{class_name}' was not found in module '{module_name}'."
        )
    return agent_class


def _instantiate_agent(agent_class: object, agent_name: str) -> object:
    component = f"agent.{agent_name}"
    if not callable(agent_class):
        raise ConfigurationError(f"Configured agent '{agent_name}' is not callable.")

    try:
        return cast(Any, agent_class)(name=agent_name, component=component)
    except TypeError:
        try:
            instance = cast(Any, agent_class)()
        except TypeError as exc:
            raise ConfigurationError(
                f"Configured agent '{agent_name}' could not be instantiated."
            ) from exc
        _configure_agent_identity(instance, agent_name, component)
        return instance


def _configure_agent_identity(agent: object, agent_name: str, component: str) -> None:
    _set_attribute(agent, "name", agent_name)
    _set_attribute(agent, "component", component)


def _apply_agent_settings(agent: object, settings: AgentPluginSettings) -> None:
    component = f"agent.{settings.name}"
    capabilities = capabilities_from_settings(settings.capabilities)
    description = (
        _read_optional_text(settings.description)
        or _read_optional_text(getattr(agent, "description", None))
        or f"Configured agent '{settings.name}'."
    )
    display_name = settings.display_name or _read_optional_text(
        getattr(agent, "display_name", None)
    )
    llm_profile = settings.llm_profile or _read_optional_text(
        getattr(agent, "default_llm_profile", None)
    )
    prompt_profile = settings.prompt_profile or _read_optional_text(
        getattr(agent, "prompt_profile", None)
    )
    metadata = _build_agent_metadata(agent, settings)

    _configure_agent_identity(agent, settings.name, component)
    _set_attribute(agent, "type", settings.type)
    _set_attribute(agent, "description", description)
    _set_attribute(agent, "display_name", display_name)
    _set_attribute(agent, "enabled", settings.enabled)
    _set_attribute(agent, "default_llm_profile", llm_profile)
    _set_attribute(agent, "prompt_profile", prompt_profile)
    _set_attribute(agent, "structured_capabilities", capabilities)
    _set_attribute(agent, "capabilities", list(capability_labels(capabilities)))
    _set_attribute(agent, "limits", settings.limits)
    _set_attribute(agent, "context_policy", settings.context_policy)
    _set_attribute(agent, "allowed_tool_intents", settings.allowed_tool_intents)
    _set_attribute(agent, "allowed_memory_scopes", settings.allowed_memory_scopes)
    _set_attribute(agent, "stream_llm_deltas", settings.stream_llm_deltas)
    _set_attribute(agent, "metadata", metadata)


def _build_agent_metadata(
    agent: object,
    settings: AgentPluginSettings,
) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if settings.expose_metadata:
        raw_metadata = getattr(agent, "metadata", None)
        if isinstance(raw_metadata, dict):
            metadata.update(raw_metadata)
        metadata.update(settings.metadata)
    metadata.update(
        {
            "entrypoint_mode": (
                "explicit_entrypoint"
                if settings.module is not None or settings.class_name is not None
                else "builtin"
            ),
            "stream_llm_deltas": settings.stream_llm_deltas,
            "allowed_tool_intent_count": len(settings.allowed_tool_intents),
            "allowed_memory_scope_count": len(settings.allowed_memory_scopes),
        }
    )
    return metadata


def _supports_structured_contract(agent: object) -> bool:
    return all(
        callable(getattr(agent, attribute, None))
        for attribute in ("run", "stream", "health", "descriptor")
    )


def _normalize_result(
    result: AgentRunResult,
    *,
    agent_name: str,
    llm_profile: str | None,
) -> AgentRunResult:
    return build_run_result(
        status=result.status,
        answer=result.answer,
        agent_name=result.agent_name or agent_name,
        llm_profile=result.llm_profile or llm_profile,
        tool_intents=result.tool_intents,
        memory_candidates=result.memory_candidates,
        review=result.review,
        usage=result.usage,
        output_items=result.output_items,
        warnings=result.warnings,
        metadata=result.metadata,
    )


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _set_attribute(agent: object, name: str, value: object) -> None:
    try:
        setattr(agent, name, value)
    except (AttributeError, TypeError):
        return


__all__ = ["AgentFactory"]