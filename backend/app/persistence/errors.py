"""Shared persistence error types and wrappers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.contracts.errors import (
    BackendError,
    ConfigurationError,
    MemoryGatewayError as ContractMemoryGatewayError,
    TraceStoreError as ContractTraceStoreError,
    WorkflowStateError as ContractWorkflowStateError,
)


class PersistenceError(BackendError):
    """Base exception for backend persistence failures."""


class PersistenceConfigurationError(ConfigurationError, PersistenceError):
    """Persistence configuration is invalid or unsupported."""


class PersistenceSerializationError(PersistenceError):
    """Persistence serialization produced an unsafe or invalid value."""


class PersistenceUnavailableError(PersistenceError):
    """Persistence infrastructure is unavailable or failed to execute."""


class WorkflowStateError(ContractWorkflowStateError, PersistenceError):
    """Workflow-state persistence failed."""

    def __init__(
        self,
        message: str = "Workflow-state persistence failed.",
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})


class WorkflowStateConfigurationError(WorkflowStateError):
    """Workflow-state persistence configuration is invalid."""


class WorkflowStateSerializationError(WorkflowStateError):
    """Workflow-state data could not be serialized or decoded safely."""


class WorkflowStateSizeError(WorkflowStateError):
    """Workflow-state payload exceeded the configured safe size limit."""


class WorkflowStateConflictError(WorkflowStateError):
    """Workflow-state write conflict detected."""


class WorkflowStateMigrationError(WorkflowStateError):
    """Workflow-state schema migration failed."""


class WorkflowStateUnavailableError(WorkflowStateError):
    """Workflow-state persistence is temporarily unavailable."""


class TraceStoreError(ContractTraceStoreError, PersistenceError):
    """Trace-store persistence failed."""


class MemoryGatewayError(ContractMemoryGatewayError, PersistenceError):
    """Memory persistence failed."""