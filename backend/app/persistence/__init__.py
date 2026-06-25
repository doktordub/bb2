"""Concrete persistence adapters for backend runtime services."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "SqliteTraceStore": (
        "app.persistence.sqlite_trace_store",
        "SqliteTraceStore",
    ),
    "SqliteWorkflowStateStore": (
        "app.persistence.sqlite_workflow_state_store",
        "SqliteWorkflowStateStore",
    ),
    "build_trace_store": (
        "app.persistence.trace_store",
        "build_trace_store",
    ),
    "build_workflow_state_store": (
        "app.persistence.workflow_state_store",
        "build_workflow_state_store",
    ),
    "resolve_trace_store_path": (
        "app.persistence.trace_store",
        "resolve_trace_store_path",
    ),
    "resolve_workflow_state_store_path": (
        "app.persistence.workflow_state_store",
        "resolve_workflow_state_store_path",
    ),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = _EXPORTS[name]
    module = import_module(module_name)
    return getattr(module, attribute_name)