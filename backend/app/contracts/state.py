"""Workflow state store contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(slots=True)
class WorkflowStateRecord:
    """Logical record describing stored workflow state."""

    session_id: str
    state: dict[str, Any]
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class WorkflowStateStore(Protocol):
    """Short-term workflow state storage contract."""

    async def load(self, session_id: str) -> dict[str, Any]:
        ...

    async def save(self, session_id: str, state: dict[str, Any]) -> None:
        ...

    async def reset(self, session_id: str) -> None:
        ...

    async def health(self) -> dict[str, Any]:
        ...