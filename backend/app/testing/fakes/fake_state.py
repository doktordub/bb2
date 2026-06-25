"""In-memory fake workflow state store for contract-focused tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.contracts.errors import WorkflowStateError
from app.contracts.state import default_workflow_state, normalize_workflow_state_session_id


class FakeWorkflowStateStore:
    """Deterministic workflow state fake backed by a dictionary."""

    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.load_requests: list[str] = []
        self.save_requests: list[tuple[str, dict[str, Any]]] = []
        self.reset_requests: list[str] = []

    async def load(self, session_id: str) -> dict[str, Any]:
        normalized_session_id = _normalize_session_id(session_id)
        self.load_requests.append(normalized_session_id)
        if normalized_session_id not in self.states:
            return default_workflow_state(normalized_session_id)
        return deepcopy(self.states[normalized_session_id])

    async def save(self, session_id: str, state: dict[str, Any]) -> None:
        normalized_session_id = _normalize_session_id(session_id)
        if not isinstance(state, dict):
            raise WorkflowStateError("Workflow-state payload must be a JSON object.")

        saved_state = deepcopy(state)
        self.save_requests.append((normalized_session_id, saved_state))
        self.states[normalized_session_id] = saved_state

    async def reset(self, session_id: str) -> None:
        normalized_session_id = _normalize_session_id(session_id)
        self.reset_requests.append(normalized_session_id)
        self.states.pop(normalized_session_id, None)

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "configured": True, "provider": "fake"}


def _normalize_session_id(session_id: object) -> str:
    try:
        return normalize_workflow_state_session_id(session_id)
    except ValueError as exc:
        raise WorkflowStateError("Invalid workflow-state session identifier.") from exc