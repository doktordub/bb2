"""Container types for the backend foundation composition root."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import TYPE_CHECKING

from app.config.settings import Settings
from app.config.view import ApiSettings, SessionSettings
from app.contracts.config import ConfigurationView
from app.deployment.startup import DeploymentStartupState
from app.contracts.llm import LLMGateway
from app.contracts.memory import MemoryGateway
from app.contracts.policy import PolicyService
from app.contracts.state import WorkflowStateStore
from app.contracts.tools import ToolGateway
from app.contracts.trace import TraceStore
from app.foundation.capabilities import CapabilitiesService
from app.foundation.health import HealthRegistry
from app.observability.debug_trace_service import DebugTraceService
from app.observability.metrics import MetricsRecorder
from app.observability.redaction import Redactor
from app.observability.tracing import TraceRecorder
from app.orchestration.runtime import OrchestrationRuntime
from app.persistence.factory import PersistenceBundle
from app.session.service import SessionService

if TYPE_CHECKING:
    from app.deployment.process_control import ProcessControlService
    from app.visualization.artifact_store import VisualizationArtifactStore
    from app.visualization.gateway import VisualizationGateway


@dataclass(frozen=True)
class FoundationContainer:
    """Shared foundation services attached to the FastAPI app state."""

    settings: Settings
    config: ConfigurationView
    deployment_startup: DeploymentStartupState
    config_summary: dict[str, object]
    redactor: Redactor
    persistence: PersistenceBundle
    workflow_state: WorkflowStateStore
    memory: MemoryGateway
    trace_store: TraceStore
    trace_recorder: TraceRecorder
    metrics: MetricsRecorder
    llm_gateway: LLMGateway
    policy_service: PolicyService
    tool_gateway: ToolGateway
    orchestrator: OrchestrationRuntime
    health: HealthRegistry
    capabilities: CapabilitiesService
    api_settings: ApiSettings | None = None
    session_settings: SessionSettings | None = None
    session_service: SessionService | None = None
    debug_trace_service: DebugTraceService | None = None
    process_control_service: ProcessControlService | None = None
    visualization_gateway: VisualizationGateway | None = None
    visualization_artifact_store: VisualizationArtifactStore | None = None

    async def close(self) -> None:
        """Close runtime services that hold open resources."""

        close = getattr(self.memory, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result
        await self.persistence.close()