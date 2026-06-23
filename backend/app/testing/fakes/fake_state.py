"""In-memory fake workflow state store for contract-focused tests."""

from __future__ import annotations

from typing import Any


class FakeWorkflowStateStore:
    """Deterministic workflow state fake backed by a dictionary."""

    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.load_requests: list[str] = []
        self.save_requests: list[tuple[str, dict[str, Any]]] = []
        self.reset_requests: list[str] = []

    async def load(self, session_id: str) -> dict[str, Any]:
        self.load_requests.append(session_id)
        return dict(self.states.get(session_id, {}))

    async def save(self, session_id: str, state: dict[str, Any]) -> None:
        self.save_requests.append((session_id, dict(state)))
        self.states[session_id] = dict(state)

    async def reset(self, session_id: str) -> None:
        self.reset_requests.append(session_id)
        self.states.pop(session_id, None)

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "provider": "fake"}