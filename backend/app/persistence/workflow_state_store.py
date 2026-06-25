"""Workflow-state store construction boundary for backend runtime wiring."""

from __future__ import annotations

from pathlib import Path

from app.contracts.config import ConfigurationView
from app.contracts.errors import ConfigurationError
from app.contracts.state import WorkflowStateStore
from app.persistence.settings import get_persistence_settings
from app.persistence.sqlite_workflow_state_store import SqliteWorkflowStateStore


async def build_workflow_state_store(config: ConfigurationView) -> WorkflowStateStore:
    """Build and initialize the configured workflow-state store implementation."""

    workflow_settings = get_persistence_settings(config).workflow_state
    if workflow_settings.provider != "sqlite" or workflow_settings.sqlite is None:
        raise ConfigurationError(
            f"Unsupported workflow-state store provider: {workflow_settings.provider}"
        )

    store = SqliteWorkflowStateStore(
        workflow_settings.sqlite.path,
        settings=workflow_settings.sqlite,
    )
    await store.initialize()
    return store


def resolve_workflow_state_store_path(config: ConfigurationView) -> Path:
    """Resolve the workflow-state SQLite path relative to the backend project root."""

    workflow_settings = get_persistence_settings(config).workflow_state
    if workflow_settings.sqlite is None:
        raise ConfigurationError(
            "Workflow-state store provider does not expose a SQLite path: "
            f"{workflow_settings.provider}"
        )
    return workflow_settings.sqlite.path