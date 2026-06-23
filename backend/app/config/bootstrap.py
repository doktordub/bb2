"""Composition-root helpers for backend foundation startup."""

from app.config.loader import YamlConfigurationLoader
from app.config.settings import Settings
from app.config.view import build_runtime_redactor, get_observability_settings
from app.contracts.config import ConfigurationView
from app.foundation.capabilities import CapabilitiesService
from app.foundation.container import FoundationContainer
from app.foundation.health import build_foundation_health_registry, build_safe_config_summary
from app.observability.logging import configure_logging_from_config
from app.observability.metrics import build_metrics_recorder
from app.observability.tracing import TraceRecorder
from app.persistence.trace_store import build_trace_store


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
    observability = get_observability_settings(config)
    trace_store = await build_trace_store(config)
    trace_recorder = TraceRecorder(
        store=trace_store,
        settings=observability,
        redactor=redactor,
    )
    metrics = build_metrics_recorder(enabled=observability.metrics_enabled)
    health = build_foundation_health_registry(
        config=config,
        config_summary=config_summary,
        redactor=redactor,
        trace_store=trace_store,
    )
    capabilities = CapabilitiesService(settings=settings, config=config)

    return FoundationContainer(
        settings=settings,
        config=config,
        config_summary=config_summary,
        redactor=redactor,
        trace_store=trace_store,
        trace_recorder=trace_recorder,
        metrics=metrics,
        health=health,
        capabilities=capabilities,
    )