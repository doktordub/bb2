"""Workflow state store contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
import re
from typing import Any, Final, Literal, Protocol, TypeAlias

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

WorkflowStateDocument: TypeAlias = dict[str, Any]


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
) -> WorkflowStateDocument:
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
    state: WorkflowStateDocument
    version: int | None = None
    found: bool = False
    loaded_empty: bool = False
    message_count: int = 0
    reset_generation: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowStateSaveResult:
    """Result metadata returned after saving workflow state."""

    session_id: str
    state: WorkflowStateDocument
    version: int
    state_size_bytes: int
    message_count: int
    reset_generation: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowStateResetResult:
    """Result metadata returned after resetting workflow state."""

    session_id: str
    version: int | None
    reset_generation: int
    cleared_version: int | None = None
    state: WorkflowStateDocument | None = None
    deleted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowSessionSummary:
    """Safe summary metadata for one persisted workflow session."""

    session_id: str
    usecase: str | None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_activity_at: datetime | None = None
    reset_count: int = 0
    message_count: int = 0


@dataclass(slots=True)
class WorkflowSessionListResult:
    """Bounded collection of safe persisted workflow-session summaries."""

    sessions: list[WorkflowSessionSummary] = field(default_factory=list)
    limit: int = 0
    has_more: bool = False


@dataclass(slots=True)
class WorkflowSessionDeleteResult:
    """Delete result for short-term workflow-session state."""

    session_id: str
    deleted: bool


class WorkflowStateStore(Protocol):
    """Short-term workflow state storage contract."""

    async def load(self, session_id: str) -> WorkflowStateRecord:
        ...

    async def save(
        self,
        session_id: str,
        state: WorkflowStateDocument,
        *,
        expected_version: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WorkflowStateSaveResult:
        ...

    async def reset(
        self,
        session_id: str,
        *,
        reason: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WorkflowStateResetResult:
        ...

    async def list_sessions(
        self,
        *,
        limit: int,
    ) -> WorkflowSessionListResult:
        ...

    async def delete_session(self, session_id: str) -> WorkflowSessionDeleteResult:
        ...

    async def health(self) -> dict[str, Any]:
        ...