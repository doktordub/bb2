"""Composition-root helpers for backend foundation startup."""

from app.config.loader import YamlConfigurationLoader
from app.config.settings import Settings
from app.config.view import (
    build_runtime_redactor,
    get_api_settings,
    get_agents_settings,
    get_observability_settings,
    get_session_settings,
)
from app.agents.health import build_agent_startup_summary
from app.contracts.config import ConfigurationView
from app.deployment.diagnostics import build_safe_deployment_summary
from app.deployment.process_control import ProcessControlService
from app.deployment.startup import validate_deployment_startup
from app.foundation.capabilities import CapabilitiesService
from app.foundation.container import FoundationContainer
from app.foundation.health import build_foundation_health_registry, build_safe_config_summary
from app.llm.factory import build_llm_runtime
from app.memory.factory import build_memory_gateway
from app.observability.debug_trace_service import DebugTraceService
from app.observability.logging import configure_logging_from_config
from app.observability.metrics import build_metrics_recorder
from app.observability.tracing import TraceRecorder
from app.orchestration.registry import AgentRegistry
from app.orchestration.runtime import DefaultOrchestrationRuntime
from app.orchestration.strategy_factory import build_strategy_registry
from app.orchestration.usecase_router import UseCaseRouter
from app.persistence.factory import build_persistence_bundle
from app.policy.factory import build_policy_runtime
from app.session.identifiers import PrefixedUuidSessionIdProvider
from app.session.service import DefaultSessionService
from app.tools.factory import build_tooling_runtime, initialize_tooling_runtime


def build_configuration_loader(settings: Settings) -> YamlConfigurationLoader:
    """Construct the real backend configuration loader from process settings."""

    return YamlConfigurationLoader(
        settings.resolved_app_config_path,
        override_path=settings.resolved_app_config_override_path,
    )


async def load_backend_config(settings: Settings) -> ConfigurationView:
    """Load the validated backend configuration view for runtime wiring."""

    loader = build_configuration_loader(settings)
    return await loader.load()


async def build_container(settings: Settings) -> FoundationContainer:
    """Assemble the validated backend container during lifespan startup."""

    config = await load_backend_config(settings)
    deployment_startup = validate_deployment_startup(settings, config)
    redactor = build_runtime_redactor(config)
    configure_logging_from_config(settings, config)
    config_summary = build_safe_config_summary(config)
    if bool(config.get("health.expose_config_summary", True)):
        config_summary["deployment"] = build_safe_deployment_summary(deployment_startup)
    api_settings = get_api_settings(config)
    observability = get_observability_settings(config)
    session_settings = get_session_settings(config)
    metrics = build_metrics_recorder(enabled=observability.metrics_enabled)
    process_control_service = ProcessControlService(
        runtime_dir=deployment_startup.paths.runtime_dir,
    )
    persistence = await build_persistence_bundle(
        config,
        observability=observability,
        metrics=metrics,
    )
    memory = await build_memory_gateway(config, persistence.settings.memory)
    policy_runtime = build_policy_runtime(config, metrics=metrics)
    trace_recorder = TraceRecorder(
        store=persistence.trace_store,
        settings=observability,
        redactor=redactor,
        policy_service=policy_runtime.service,
        config=config,
    )
    llm_runtime = build_llm_runtime(
        config,
        policy_service=policy_runtime.service,
        metrics=metrics,
    )
    tooling_runtime = build_tooling_runtime(config)
    await initialize_tooling_runtime(tooling_runtime)
    agent_settings = get_agents_settings(config)
    agent_registry = AgentRegistry.from_config(config)
    if bool(config.get("health.expose_config_summary", True)):
        config_summary["agents"] = build_agent_startup_summary(
            settings=agent_settings,
            registry=agent_registry,
        )
    strategy_registry = build_strategy_registry(config)
    orchestrator = DefaultOrchestrationRuntime(
        config=config,
        llm_gateway=llm_runtime.gateway,
        memory=memory,
        trace_recorder=trace_recorder,
        policy_service=policy_runtime.service,
        agent_registry=agent_registry,
        strategy_registry=strategy_registry,
        usecase_router=UseCaseRouter(config),
        tools=tooling_runtime.gateway,
    )
    if bool(config.get("health.expose_config_summary", True)):
        orchestration_health = await orchestrator.health()
        config_summary["orchestration"] = {
            "enabled": orchestration_health.enabled,
            "registry_ready": orchestration_health.registry_ready,
            "default_strategy": orchestration_health.default_strategy,
            "fallback_strategy": orchestration_health.fallback_strategy,
            "strategies_configured": orchestration_health.configured_strategy_count,
            "strategies_enabled": orchestration_health.enabled_strategy_count,
            "strategies_registered": orchestration_health.registered_strategy_count,
            "strategies_ready": orchestration_health.metadata.get("strategies_ready_count", 0),
            "strategy_types": orchestration_health.metadata.get("strategy_types", []),
            "usecases_configured": orchestration_health.configured_usecase_count,
            "usecases_enabled": orchestration_health.enabled_usecase_count,
            "agents_configured": orchestration_health.configured_agent_count,
        }
    health = build_foundation_health_registry(
        config=config,
        config_summary=config_summary,
        redactor=redactor,
        persistence=persistence,
        llm_gateway=llm_runtime.gateway,
        memory_gateway=memory,
        tool_gateway=tooling_runtime.gateway,
        orchestrator=orchestrator,
    )
    session_service = DefaultSessionService(
        config=config,
        settings=session_settings,
        workflow_state=persistence.workflow_state,
        trace_recorder=trace_recorder,
        orchestrator=orchestrator,
        policy_service=policy_runtime.service,
        id_provider=PrefixedUuidSessionIdProvider(prefix=session_settings.identifiers.prefix),
    )
    capabilities = CapabilitiesService(
        settings=settings,
        config=config,
        session_settings=session_settings,
        session_service_available=session_service is not None,
        llm_gateway=llm_runtime.gateway,
        memory_gateway=memory,
        tool_gateway=tooling_runtime.gateway,
        orchestrator=orchestrator,
        policy_service=policy_runtime.service,
        process_control_service=process_control_service,
    )
    debug_trace_service = DebugTraceService(
        trace_store=persistence.trace_store,
        max_trace_events=api_settings.debug_routes.max_trace_events,
        max_search_results=api_settings.debug_routes.max_search_results,
    )

    return FoundationContainer(
        settings=settings,
        config=config,
        deployment_startup=deployment_startup,
        config_summary=config_summary,
        redactor=redactor,
        persistence=persistence,
        workflow_state=persistence.workflow_state,
        memory=memory,
        trace_store=persistence.trace_store,
        trace_recorder=trace_recorder,
        metrics=metrics,
        llm_gateway=llm_runtime.gateway,
        policy_service=policy_runtime.service,
        tool_gateway=tooling_runtime.gateway,
        orchestrator=orchestrator,
        health=health,
        capabilities=capabilities,
        api_settings=api_settings,
        session_settings=session_settings,
        session_service=session_service,
        debug_trace_service=debug_trace_service,
        process_control_service=process_control_service,
    )