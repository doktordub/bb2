"""Composition-root helpers for backend foundation startup."""

from app.config.loader import load_raw_config
from app.config.settings import Settings
from app.foundation.capabilities import CapabilitiesService
from app.foundation.container import FoundationContainer
from app.foundation.health import build_foundation_health_registry


def build_container(settings: Settings) -> FoundationContainer:
    """Assemble the minimal foundation container without touching external systems."""

    raw_config = load_raw_config(
        settings.app_config_path,
        active_usecase=settings.app_usecase,
        strict=settings.app_config_strict,
    )
    health = build_foundation_health_registry(settings=settings, raw_config=raw_config)
    capabilities = CapabilitiesService(settings=settings, raw_config=raw_config)

    return FoundationContainer(
        settings=settings,
        raw_config=raw_config,
        health=health,
        capabilities=capabilities,
    )