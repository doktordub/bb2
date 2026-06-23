"""Container types for the backend foundation composition root."""

from dataclasses import dataclass

from app.contracts.config import ConfigurationView
from app.contracts.trace import TraceStore
from app.config.settings import Settings
from app.foundation.capabilities import CapabilitiesService
from app.foundation.health import HealthRegistry
from app.observability.metrics import MetricsRecorder
from app.observability.redaction import Redactor
from app.observability.tracing import TraceRecorder


@dataclass(frozen=True)
class FoundationContainer:
    """Shared foundation services attached to the FastAPI app state."""

    settings: Settings
    config: ConfigurationView
    config_summary: dict[str, object]
    redactor: Redactor
    trace_store: TraceStore
    trace_recorder: TraceRecorder
    metrics: MetricsRecorder
    health: HealthRegistry
    capabilities: CapabilitiesService