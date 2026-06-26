"""Composition-root helpers for backend foundation startup."""

from app.config.loader import YamlConfigurationLoader
from app.config.settings import Settings
from app.config.view import (
    build_runtime_redactor,
    get_api_settings,
    get_observability_settings,
)
from app.contracts.config import ConfigurationView
from app.foundation.capabilities import CapabilitiesService
from app.foundation.container import FoundationContainer
from app.foundation.health import build_foundation_health_registry, build_safe_config_summary
from app.observability.debug_trace_service import DebugTraceService
from app.observability.logging import configure_logging_from_config
from app.observability.metrics import build_metrics_recorder
from app.observability.tracing import TraceRecorder
from app.persistence.factory import build_persistence_bundle
from app.testing.fakes.fake_session_service import FakeSessionService


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
    redactor = build_runtime_redactor(config)
    configure_logging_from_config(settings, config)
    config_summary = build_safe_config_summary(config)
    api_settings = get_api_settings(config)
    observability = get_observability_settings(config)
    metrics = build_metrics_recorder(enabled=observability.metrics_enabled)
    persistence = await build_persistence_bundle(
        config,
        observability=observability,
        metrics=metrics,
    )
    trace_recorder = TraceRecorder(
        store=persistence.trace_store,
        settings=observability,
        redactor=redactor,
    )
    health = build_foundation_health_registry(
        config=config,
        config_summary=config_summary,
        redactor=redactor,
        persistence=persistence,
    )
    capabilities = CapabilitiesService(settings=settings, config=config)
    session_service = FakeSessionService()
    debug_trace_service = DebugTraceService(
        trace_store=persistence.trace_store,
        max_trace_events=api_settings.debug_routes.max_trace_events,
        max_search_results=api_settings.debug_routes.max_search_results,
    )

    return FoundationContainer(
        settings=settings,
        config=config,
        config_summary=config_summary,
        redactor=redactor,
        persistence=persistence,
        workflow_state=persistence.workflow_state,
        memory=persistence.memory,
        trace_store=persistence.trace_store,
        trace_recorder=trace_recorder,
        metrics=metrics,
        health=health,
        capabilities=capabilities,
        api_settings=api_settings,
        session_service=session_service,
        debug_trace_service=debug_trace_service,
    )