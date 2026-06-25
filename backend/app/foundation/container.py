"""Container types for the backend foundation composition root."""

from dataclasses import dataclass

from app.contracts.config import ConfigurationView
from app.contracts.memory import MemoryGateway
from app.contracts.state import WorkflowStateStore
from app.contracts.trace import TraceStore
from app.config.settings import Settings
from app.foundation.capabilities import CapabilitiesService
from app.foundation.health import HealthRegistry
from app.observability.metrics import MetricsRecorder
from app.observability.redaction import Redactor
from app.observability.tracing import TraceRecorder
from app.persistence.factory import PersistenceBundle


@dataclass(frozen=True)
class FoundationContainer:
    """Shared foundation services attached to the FastAPI app state."""

    settings: Settings
    config: ConfigurationView
    config_summary: dict[str, object]
    redactor: Redactor
    persistence: PersistenceBundle
    workflow_state: WorkflowStateStore
    memory: MemoryGateway
    trace_store: TraceStore
    trace_recorder: TraceRecorder
    metrics: MetricsRecorder
    health: HealthRegistry
    capabilities: CapabilitiesService