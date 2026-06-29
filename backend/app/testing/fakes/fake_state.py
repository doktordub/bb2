"""In-memory fake workflow state store for contract-focused tests."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from typing import Any

from app.contracts.errors import WorkflowStateError
from app.contracts.state import (
    WorkflowSessionDeleteResult,
    WorkflowSessionListResult,
    WorkflowSessionSummary,
    WorkflowStateRecord,
    WorkflowStateResetResult,
    WorkflowStateSaveResult,
    default_workflow_state,
    normalize_workflow_state_session_id,
)
from app.persistence.errors import WorkflowStateConflictError


@dataclass(frozen=True, slots=True)
class FakeWorkflowStateSaveCall:
    """Recorded fake save invocation including optimistic concurrency inputs."""

    session_id: str
    state: dict[str, Any]
    expected_version: int | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FakeWorkflowStateResetCall:
    """Recorded fake reset invocation including optional metadata."""

    session_id: str
    reason: str | None
    metadata: dict[str, Any]


@dataclass(slots=True)
class _FakeWorkflowSession:
    session_id: str
    usecase: str | None = None
    status: str = "active"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_activity_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reset_count: int = 0


class FakeWorkflowStateStore:
    """Deterministic workflow state fake backed by a dictionary."""

    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.versions: dict[str, int] = {}
        self.reset_generations: dict[str, int] = {}
        self.sessions: dict[str, _FakeWorkflowSession] = {}
        self.load_requests: list[str] = []
        self.list_limits: list[int] = []
        self.save_requests: list[tuple[str, dict[str, Any]]] = []
        self.save_calls: list[FakeWorkflowStateSaveCall] = []
        self.delete_requests: list[str] = []
        self.reset_requests: list[str] = []
        self.reset_calls: list[FakeWorkflowStateResetCall] = []
        self.conflict_on_next_save: set[str] = set()

    async def load(self, session_id: str) -> WorkflowStateRecord:
        normalized_session_id = _normalize_session_id(session_id)
        self.load_requests.append(normalized_session_id)
        if normalized_session_id not in self.states:
            return WorkflowStateRecord(
                session_id=normalized_session_id,
                state=default_workflow_state(normalized_session_id),
                version=None,
                found=False,
                loaded_empty=True,
                message_count=0,
                reset_generation=self.reset_generations.get(normalized_session_id, 0),
            )

        state = deepcopy(self.states[normalized_session_id])
        return WorkflowStateRecord(
            session_id=normalized_session_id,
            state=state,
            version=self.versions[normalized_session_id],
            found=True,
            loaded_empty=bool(state.get("metadata", {}).get("loaded_empty", False)),
            message_count=_message_count(state),
            reset_generation=self.reset_generations.get(normalized_session_id, 0),
        )

    async def save(
        self,
        session_id: str,
        state: dict[str, Any],
        *,
        expected_version: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WorkflowStateSaveResult:
        normalized_session_id = _normalize_session_id(session_id)
        if not isinstance(state, dict):
            raise WorkflowStateError("Workflow-state payload must be a JSON object.")

        current_version = self.versions.get(normalized_session_id)
        if normalized_session_id in self.conflict_on_next_save:
            self.conflict_on_next_save.remove(normalized_session_id)
            raise WorkflowStateConflictError(
                "Workflow-state save conflicted with the current version.",
                details={
                    "session_id": normalized_session_id,
                    "expected_version": expected_version,
                    "actual_version": current_version,
                },
            )

        if expected_version is not None and current_version != expected_version:
            raise WorkflowStateConflictError(
                "Workflow-state save conflicted with the current version.",
                details={
                    "session_id": normalized_session_id,
                    "expected_version": expected_version,
                    "actual_version": current_version,
                },
            )

        saved_state = deepcopy(state)
        self.save_requests.append((normalized_session_id, saved_state))
        self.save_calls.append(
            FakeWorkflowStateSaveCall(
                session_id=normalized_session_id,
                state=deepcopy(saved_state),
                expected_version=expected_version,
                metadata=dict(metadata or {}),
            )
        )
        self.states[normalized_session_id] = saved_state
        self._touch_session(normalized_session_id, metadata=dict(metadata or {}))
        next_version = 1 if current_version is None else current_version + 1
        self.versions[normalized_session_id] = next_version

        return WorkflowStateSaveResult(
            session_id=normalized_session_id,
            state=deepcopy(saved_state),
            version=next_version,
            state_size_bytes=len(json.dumps(saved_state, sort_keys=True).encode("utf-8")),
            message_count=_message_count(saved_state),
            reset_generation=self.reset_generations.get(normalized_session_id, 0),
        )

    async def reset(
        self,
        session_id: str,
        *,
        reason: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WorkflowStateResetResult:
        normalized_session_id = _normalize_session_id(session_id)
        self.reset_requests.append(normalized_session_id)
        self.reset_calls.append(
            FakeWorkflowStateResetCall(
                session_id=normalized_session_id,
                reason=reason,
                metadata=dict(metadata or {}),
            )
        )
        cleared_version = self.versions.pop(normalized_session_id, None)
        self.states.pop(normalized_session_id, None)
        next_reset_generation = self.reset_generations.get(normalized_session_id, 0) + 1
        self.reset_generations[normalized_session_id] = next_reset_generation
        self._touch_session(
            normalized_session_id,
            metadata=dict(metadata or {}),
            increment_reset=True,
        )

        return WorkflowStateResetResult(
            session_id=normalized_session_id,
            version=None,
            reset_generation=next_reset_generation,
            cleared_version=cleared_version,
            state=None,
            deleted=True,
        )

    async def list_sessions(self, *, limit: int) -> WorkflowSessionListResult:
        normalized_limit = _normalize_list_limit(limit)
        self.list_limits.append(normalized_limit)

        ordered_sessions = sorted(
            self.sessions.values(),
            key=lambda session: (session.last_activity_at, session.session_id),
            reverse=True,
        )
        limited_sessions = ordered_sessions[:normalized_limit]

        return WorkflowSessionListResult(
            sessions=[
                WorkflowSessionSummary(
                    session_id=session.session_id,
                    usecase=session.usecase,
                    status=session.status,
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                    last_activity_at=session.last_activity_at,
                    reset_count=session.reset_count,
                    message_count=_message_count(self.states.get(session.session_id, {})),
                )
                for session in limited_sessions
            ],
            limit=normalized_limit,
            has_more=len(ordered_sessions) > normalized_limit,
        )

    async def delete_session(self, session_id: str) -> WorkflowSessionDeleteResult:
        normalized_session_id = _normalize_session_id(session_id)
        self.delete_requests.append(normalized_session_id)

        deleted = normalized_session_id in self.sessions
        self.sessions.pop(normalized_session_id, None)
        self.states.pop(normalized_session_id, None)
        self.versions.pop(normalized_session_id, None)
        self.reset_generations.pop(normalized_session_id, None)
        self.conflict_on_next_save.discard(normalized_session_id)

        return WorkflowSessionDeleteResult(
            session_id=normalized_session_id,
            deleted=deleted,
        )

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "configured": True, "provider": "fake"}

    def queue_conflict(self, session_id: str) -> None:
        self.conflict_on_next_save.add(_normalize_session_id(session_id))

    def _touch_session(
        self,
        session_id: str,
        *,
        metadata: Mapping[str, Any],
        increment_reset: bool = False,
    ) -> None:
        now = datetime.now(UTC)
        existing = self.sessions.get(session_id)
        usecase = _optional_text(metadata.get("usecase"))

        if existing is None:
            existing = _FakeWorkflowSession(session_id=session_id, usecase=usecase)
            self.sessions[session_id] = existing
        elif usecase is not None:
            existing.usecase = usecase

        existing.status = "active"
        existing.updated_at = now
        existing.last_activity_at = now
        if increment_reset:
            existing.reset_count += 1


def _normalize_session_id(session_id: object) -> str:
    try:
        return normalize_workflow_state_session_id(session_id)
    except ValueError as exc:
        raise WorkflowStateError("Invalid workflow-state session identifier.") from exc


def _message_count(state: dict[str, Any]) -> int:
    conversation = state.get("conversation")
    if not isinstance(conversation, dict):
        return 0

    messages = conversation.get("messages")
    if not isinstance(messages, list):
        return 0

    return len(messages)


def _normalize_list_limit(limit: object) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise WorkflowStateError("Workflow-state session list limit must be a positive integer.")

    return limit


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    return normalized or None