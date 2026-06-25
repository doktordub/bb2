"""Workflow state store contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import re
from typing import Any, Final, Literal, Protocol

WorkflowStateResetMode = Literal[
    "replace_with_empty_state",
    "delete_state_row",
]

WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE: Final[WorkflowStateResetMode] = "replace_with_empty_state"
WORKFLOW_STATE_RESET_MODE_DELETE_STATE_ROW: Final[WorkflowStateResetMode] = "delete_state_row"
WORKFLOW_STATE_RESET_MODES: Final[frozenset[WorkflowStateResetMode]] = frozenset(
    {
        WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE,
        WORKFLOW_STATE_RESET_MODE_DELETE_STATE_ROW,
    }
)
DEFAULT_WORKFLOW_STATE_VERSION = 1
_WORKFLOW_STATE_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{3,128}$")


def normalize_workflow_state_session_id(session_id: object) -> str:
    """Validate and normalize a workflow-state session identifier."""

    if not isinstance(session_id, str):
        raise ValueError("Invalid workflow-state session identifier.")

    normalized = session_id.strip()
    if not _WORKFLOW_STATE_SESSION_ID_PATTERN.fullmatch(normalized):
        raise ValueError("Invalid workflow-state session identifier.")

    return normalized


def default_workflow_state(
    session_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the canonical default state for a session with no saved workflow state."""

    normalized_session_id = normalize_workflow_state_session_id(session_id)
    timestamp = (now or datetime.now(UTC)).isoformat()
    return {
        "version": DEFAULT_WORKFLOW_STATE_VERSION,
        "session_id": normalized_session_id,
        "conversation": {"messages": []},
        "workflow": {
            "current_step": None,
            "checkpoint": None,
            "scratch": {},
            "pending_actions": [],
        },
        "last_result": {
            "agent_name": None,
            "strategy_name": None,
            "llm_profile": None,
        },
        "metadata": {
            "created_at": timestamp,
            "loaded_empty": True,
        },
    }


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