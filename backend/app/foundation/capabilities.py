"""Foundation-safe capability discovery."""

from __future__ import annotations

from typing import Any, cast

from app.config.settings import Settings
from app.config.view import (
    ApiSettings,
    SessionSettings,
    get_agents_settings,
    get_orchestration_settings,
    get_tooling_settings,
    get_visualization_settings,
)
from app.contracts.config import ConfigurationView
from app.deployment.process_control import ProcessControlService
from app.contracts.llm import LLMGateway
from app.contracts.memory import MemoryGateway, MemoryHealthResult
from app.contracts.policy import PolicyService
from app.contracts.tools import ToolGateway
from app.orchestration.capabilities import (
    OrchestrationCapabilitiesResult,
    OrchestrationUseCaseCapability,
    build_orchestration_capabilities,
)
from app.policy.capabilities import (
    build_capabilities_policy_request,
    sanitize_capabilities_payload,
)
from app.policy.context import build_readonly_policy_context
from app.policy.settings import PolicyProfileSettings
from app.orchestration.runtime import OrchestrationRuntime
from app.orchestration.strategy_factory import build_strategy_registry
from app.tools.capabilities import build_tool_capabilities_payload
from app.visualization.capabilities import build_visualization_capabilities_payload
from app.visualization.chart_registry import ChartTypeRegistry


class CapabilitiesService:
    """Expose the backend feature surface without leaking implementation details."""

    def __init__(
        self,
        *,
        settings: Settings,
        config: ConfigurationView,
        session_settings: SessionSettings | None = None,
        session_service_available: bool = False,
        llm_gateway: LLMGateway | None = None,
        memory_gateway: MemoryGateway | None = None,
        tool_gateway: ToolGateway | None = None,
        orchestrator: OrchestrationRuntime | None = None,
        policy_service: PolicyService | None = None,
        process_control_service: ProcessControlService | None = None,
    ) -> None:
        self._settings = settings
        self._config = config
        self._session_settings = session_settings
        self._session_service_available = session_service_available
        self._llm_gateway = llm_gateway
        self._memory_gateway = memory_gateway
        self._tool_gateway = tool_gateway
        self._orchestrator = orchestrator
        self._policy_service = policy_service
        self._process_control_service = process_control_service

    def describe(self) -> dict[str, Any]:
        features = self._config.section("features")
        orchestration_enabled, enabled_usecases = self._configured_usecases()
        chat_enabled = orchestration_enabled and bool(enabled_usecases)
        tool_capabilities = self._describe_tool_capabilities_fallback()
        visualization_settings = get_visualization_settings(self._config)

        return {
            "service": self._config.require("app.name"),
            "capabilities": {
                "chat": chat_enabled,
                "streaming": bool(features.get("streaming_enabled", False)) and chat_enabled,
                "session_reset": chat_enabled
                and self._has_provider("persistence.workflow_state.provider"),
                "tools": tool_capabilities,
                "memory": bool(features.get("memory_enabled", False))
                and self._has_provider("persistence.memory.provider"),
                "llm_profiles": bool(self._config.section("llm.profiles")),
                "trace": bool(features.get("trace_enabled", False))
                and self._has_provider("persistence.trace.provider"),
                "visualization": visualization_settings.enabled,
            },
        }

    async def describe_api(
        self,
        *,
        api_settings: ApiSettings,
        trace_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Return the frontend-safe capability view."""

        features = self._config.section("features")
        orchestration = await self._orchestration_capabilities()
        chat_enabled = orchestration.enabled and bool(orchestration.usecases)
        llm_capabilities = await self._describe_llm_capabilities()
        memory_capabilities = await self._describe_memory_capabilities()
        tool_capabilities = await self._describe_tool_capabilities()
        profile = self._resolve_policy_profile() if self._policy_service is not None else None
        visualization_capabilities = self._describe_visualization_capabilities(profile=profile)

        payload = {
            "chat": {
                "enabled": chat_enabled,
                "streaming_enabled": bool(features.get("streaming_enabled", False))
                and chat_enabled,
                "max_message_chars": api_settings.request_limits.max_message_chars,
            },
            "sessions": {
                "reset_enabled": chat_enabled
                and self._has_provider("persistence.workflow_state.provider"),
                "history_enabled": self._history_enabled(chat_enabled=chat_enabled),
                "list_enabled": self._list_enabled(chat_enabled=chat_enabled),
                "delete_enabled": self._delete_enabled(chat_enabled=chat_enabled),
                "client_session_id_enabled": api_settings.sessions.accept_client_session_id,
                "continuity_enabled": self._continuity_enabled(chat_enabled=chat_enabled),
                "continuity_mode": self._continuity_mode(chat_enabled=chat_enabled),
                "summary_compaction_enabled": self._summary_compaction_enabled(chat_enabled=chat_enabled),
            },
            "usecases": [
                {
                    "name": usecase.name,
                    "display_name": usecase.display_name or _display_name(usecase.name),
                    "description": usecase.description,
                    "strategy_type": usecase.strategy_type,
                    "streaming_supported": usecase.streaming_supported,
                    "memory_enabled": usecase.memory_enabled,
                    "tools_enabled": usecase.tools_enabled,
                }
                for usecase in orchestration.usecases
            ],
            "agents": [
                {
                    "name": agent.name,
                    "display_name": agent.display_name,
                    "type": agent.type,
                    "streaming_supported": agent.streaming_supported,
                    "capabilities": list(agent.capabilities),
                }
                for agent in orchestration.agents
            ],
            "debug": {
                "trace_routes_enabled": api_settings.debug_routes.enabled,
                "restart_enabled": self._restart_enabled(api_settings=api_settings),
            },
            "tools": tool_capabilities,
            "memory": memory_capabilities,
            "llm": llm_capabilities,
            "visualization": visualization_capabilities,
        }

        if self._policy_service is not None and hasattr(self._policy_service, "health"):
            payload["policy"] = {
                "configured": True,
                "enabled": True,
                "mode": getattr(getattr(self._policy_service, "_settings", None), "mode", "enforce"),
            }

        if self._policy_service is None:
            return payload

        policy_context = build_readonly_policy_context(
            policy_service=self._policy_service,
            config=self._config,
            trace_id=trace_id,
            user_id=user_id,
        )
        request = build_capabilities_policy_request(
            trace_id=trace_id,
            user_id=user_id,
            payload=payload,
        )
        decision = await self._policy_service.evaluate(request, policy_context)
        if decision.is_denied:
            return {
                "chat": {
                    "enabled": False,
                    "streaming_enabled": False,
                    "max_message_chars": api_settings.request_limits.max_message_chars,
                },
                "sessions": {
                    "reset_enabled": False,
                    "history_enabled": False,
                    "list_enabled": False,
                    "delete_enabled": False,
                    "client_session_id_enabled": api_settings.sessions.accept_client_session_id,
                    "continuity_enabled": False,
                    "continuity_mode": "disabled",
                    "summary_compaction_enabled": False,
                },
                "usecases": [],
                "agents": [],
                "debug": {
                    "trace_routes_enabled": False,
                    "restart_enabled": False,
                },
                "tools": {
                    "enabled": False,
                    "configured": False,
                    "streaming_supported": False,
                    "total_tools": 0,
                    "approval_required_tools": 0,
                    "safety_levels": {},
                    "transport": None,
                    "discovery_enabled": False,
                },
                "memory": {
                    "enabled": False,
                    "configured": False,
                    "provider": None,
                    "search_available": False,
                    "ingest_available": False,
                },
                "llm": {
                    "enabled": False,
                    "default_profile": None,
                    "streaming_supported": False,
                    "structured_output_supported": False,
                },
                "visualization": {
                    "enabled": False,
                    "default_renderer": None,
                    "allowed_renderers": [],
                    "spec_version": None,
                    "context_summary_mode": "disabled",
                    "supported_chart_types": [],
                    "reference_mode_supported": False,
                    "reference_mode_enabled": False,
                    "artifact_store_enabled": False,
                    "exact_followup_retrieval_enabled": False,
                    "limits": {},
                },
            }
        profile = profile or self._resolve_policy_profile()
        return sanitize_capabilities_payload(payload, profile=profile)

    def _describe_visualization_capabilities(
        self,
        *,
        profile: PolicyProfileSettings | None,
    ) -> dict[str, Any]:
        settings = get_visualization_settings(self._config)
        registry = ChartTypeRegistry(
            allowed_chart_types=settings.allowed_chart_types,
            aliases=settings.aliases,
        )
        return build_visualization_capabilities_payload(
            settings=settings,
            registry=registry,
            policy=(profile.visualization if profile is not None else None),
        )

    def _resolve_policy_profile(self) -> PolicyProfileSettings:
        if self._policy_service is None:
            raise RuntimeError("Policy service is not configured.")
        engine = getattr(self._policy_service, "engine", None)
        if engine is None:
            raise RuntimeError("Policy engine is not available.")
        settings = getattr(engine, "_settings", None)
        if settings is None:
            raise RuntimeError("Policy settings are not available.")
        profile_name = settings.default_profile or "default"
        return cast(PolicyProfileSettings, settings.profiles[profile_name])

    async def _enabled_usecases(self) -> tuple[bool, list[OrchestrationUseCaseCapability]]:
        if self._orchestrator is not None:
            try:
                capabilities = await self._orchestrator.capabilities()
            except Exception:
                return self._configured_usecases()
            return capabilities.enabled, sorted(capabilities.usecases, key=lambda item: item.name)

        return self._configured_usecases()

    async def _orchestration_capabilities(self) -> OrchestrationCapabilitiesResult:
        if self._orchestrator is not None:
            try:
                return await self._orchestrator.capabilities()
            except Exception:
                return self._configured_orchestration_capabilities()
        return self._configured_orchestration_capabilities()

    def _configured_orchestration_capabilities(self) -> OrchestrationCapabilitiesResult:
        settings = get_orchestration_settings(self._config)
        return build_orchestration_capabilities(
            settings,
            strategy_registry=build_strategy_registry(self._config),
            agent_settings=get_agents_settings(self._config),
        )

    def _configured_usecases(self) -> tuple[bool, list[OrchestrationUseCaseCapability]]:
        settings = get_orchestration_settings(self._config)
        if not settings.enabled:
            return False, []

        capabilities = build_orchestration_capabilities(
            settings,
            strategy_registry=build_strategy_registry(self._config),
        )
        return capabilities.enabled, sorted(capabilities.usecases, key=lambda item: item.name)

    def _has_provider(self, path: str) -> bool:
        value = self._config.get(path)
        return isinstance(value, str) and value.strip() != ""

    def _history_enabled(self, *, chat_enabled: bool) -> bool:
        return (
            chat_enabled
            and self._session_service_available
            and self._session_settings is not None
            and self._session_settings.history.enabled
            and self._has_provider("persistence.workflow_state.provider")
        )

    def _list_enabled(self, *, chat_enabled: bool) -> bool:
        return (
            chat_enabled
            and self._session_service_available
            and self._session_settings is not None
            and self._session_settings.management.list_enabled
            and self._has_provider("persistence.workflow_state.provider")
        )

    def _delete_enabled(self, *, chat_enabled: bool) -> bool:
        return (
            chat_enabled
            and self._session_service_available
            and self._session_settings is not None
            and self._session_settings.management.delete_enabled
            and self._has_provider("persistence.workflow_state.provider")
        )

    def _continuity_enabled(self, *, chat_enabled: bool) -> bool:
        if not chat_enabled:
            return False
        settings = get_orchestration_settings(self._config).defaults.conversation_context
        return settings.enabled and self._has_provider("persistence.workflow_state.provider")

    def _continuity_mode(self, *, chat_enabled: bool) -> str:
        if not self._continuity_enabled(chat_enabled=chat_enabled):
            return "disabled"
        settings = get_orchestration_settings(self._config).defaults.conversation_context
        return settings.mode

    def _summary_compaction_enabled(self, *, chat_enabled: bool) -> bool:
        if not self._continuity_enabled(chat_enabled=chat_enabled):
            return False
        settings = get_orchestration_settings(self._config).defaults.conversation_context
        return settings.summary_max_chars > 0 and settings.summary_threshold_messages >= settings.max_messages

    def _restart_enabled(self, *, api_settings: ApiSettings) -> bool:
        return (
            api_settings.debug_routes.enabled
            and api_settings.debug_routes.restart_enabled
            and self._process_control_service is not None
            and self._process_control_service.restart_supported
        )

    async def _describe_llm_capabilities(self) -> dict[str, Any]:
        default_profile = _read_optional_str(self._config.get("llm.defaults.profile"))
        if self._llm_gateway is None:
            return {
                "enabled": bool(self._config.section("llm.profiles")),
                "default_profile": default_profile,
                "streaming_supported": False,
                "structured_output_supported": False,
            }

        profiles = await self._llm_gateway.list_profiles()
        enabled_profiles = [profile for profile in profiles if profile.enabled]
        return {
            "enabled": bool(enabled_profiles),
            "default_profile": default_profile,
            "streaming_supported": any(profile.supports_streaming for profile in enabled_profiles),
            "structured_output_supported": any(
                profile.supports_json_schema for profile in enabled_profiles
            ),
        }

    async def _describe_memory_capabilities(self) -> dict[str, Any]:
        configured_provider = _read_optional_str(self._config.get("memory.provider")) or _read_optional_str(
            self._config.get("persistence.memory.provider")
        )

        if self._memory_gateway is None:
            configured_enabled = self._config.get("memory.enabled")
            if not isinstance(configured_enabled, bool):
                configured_enabled = bool(self._config.section("features").get("memory_enabled", False))
            return {
                "enabled": configured_enabled,
                "configured": configured_provider is not None,
                "provider": configured_provider,
                "search_available": False,
                "ingest_available": False,
            }

        health = await self._memory_gateway.health()
        payload = dict(health) if isinstance(health, MemoryHealthResult) else dict(health)
        return {
            "enabled": bool(payload.get("enabled", False)),
            "configured": bool(payload.get("configured", False)),
            "provider": _read_optional_str(payload.get("provider")),
            "search_available": bool(payload.get("search_available", False)),
            "ingest_available": bool(payload.get("ingest_available", False)),
        }

    async def _describe_tool_capabilities(self) -> dict[str, Any]:
        if self._tool_gateway is None:
            return self._describe_tool_capabilities_fallback()

        capabilities = await self._tool_gateway.capabilities()
        return build_tool_capabilities_payload(capabilities)

    def _describe_tool_capabilities_fallback(self) -> dict[str, Any]:
        tooling = get_tooling_settings(self._config)
        safety_levels = {
            "read_only": 0,
            "write": 0,
            "destructive": 0,
            "external_side_effect": 0,
        }
        approval_required_tools = 0
        enabled_tools = 0
        streaming_supported = False

        for definition in tooling.registry.tools.values():
            if not definition.enabled:
                continue
            enabled_tools += 1
            safety_levels[definition.safety_level] = (
                safety_levels.get(definition.safety_level, 0) + 1
            )
            if definition.approval_required:
                approval_required_tools += 1
            execution_modes = definition.extra.get("execution_modes")
            if isinstance(execution_modes, list) and "stream" in execution_modes:
                streaming_supported = True
            if definition.extra.get("supports_streaming") is True:
                streaming_supported = True

        return {
            "enabled": tooling.enabled,
            "configured": bool(tooling.mcp_server.endpoint),
            "streaming_supported": streaming_supported,
            "total_tools": enabled_tools,
            "approval_required_tools": approval_required_tools,
            "safety_levels": safety_levels,
            "transport": tooling.mcp_server.transport,
            "discovery_enabled": tooling.mcp_server.tool_discovery_enabled,
        }


def _display_name(name: str) -> str:
    return name.replace("_", " ").strip().title()


def _read_optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None