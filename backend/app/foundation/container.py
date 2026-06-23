"""Container types for the backend foundation composition root."""

from dataclasses import dataclass
from typing import Any

from app.config.settings import Settings
from app.foundation.capabilities import CapabilitiesService
from app.foundation.health import HealthRegistry


@dataclass(frozen=True)
class FoundationContainer:
    """Shared foundation services attached to the FastAPI app state."""

    settings: Settings
    raw_config: dict[str, Any]
    health: HealthRegistry
    capabilities: CapabilitiesService