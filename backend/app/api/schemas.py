"""API request and response DTOs for the backend boundary."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.contracts.results import OrchestrationResult
from app.observability.redaction import SENSITIVE_KEY_PARTS, is_sensitive_key
from app.session.models import SessionChatResult, SessionResetResult

SCHEMA_VERSION = "1.0"
_DEFAULT_MAX_MESSAGE_CHARS = 20000
_DEFAULT_MAX_METADATA_BYTES = 65536


class ChatRequest(BaseModel):
    """Public request payload for non-streaming and streaming chat endpoints."""

    message: str = Field(min_length=1, max_length=_DEFAULT_MAX_MESSAGE_CHARS)
    session_id: str | None = Field(default=None, min_length=3, max_length=128)
    usecase: str | None = Field(default=None, min_length=1, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be empty")
        return normalized

    @field_validator("session_id")
    @classmethod
    def normalize_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("session_id must not be empty")
        return normalized

    @field_validator("usecase")
    @classmethod
    def normalize_usecase(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("usecase must not be empty")
        return normalized

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_metadata(value)
        return value


class ChatResponseData(BaseModel):
    """Response body for chat results."""

    answer: str
    agent_name: str | None = None
    strategy_name: str | None = None
    llm_profile: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    memory_updates: list[dict[str, Any]] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """Stable public response envelope for chat operations."""

    schema_version: str = SCHEMA_VERSION
    trace_id: str
    session_id: str
    data: ChatResponseData
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_result(cls, result: SessionChatResult) -> ChatResponse:
        return cls(
            trace_id=result.trace_id,
            session_id=result.session_id,
            data=ChatResponseData(
                answer=result.answer,
                agent_name=result.agent_name,
                strategy_name=result.strategy_name,
                llm_profile=result.llm_profile,
                tool_calls=[dict(item) for item in result.tool_calls],
                memory_updates=[dict(item) for item in result.memory_updates],
            ),
            metadata=dict(result.metadata),
        )


class ResetSessionRequest(BaseModel):
    """Public request payload for session reset."""

    reason: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason must not be empty")
        return normalized


class ResetSessionResponseData(BaseModel):
    """Response body for session reset."""

    reset: bool
    message: str


class ResetSessionResponse(BaseModel):
    """Stable public response envelope for session reset."""

    schema_version: str = SCHEMA_VERSION
    trace_id: str
    session_id: str
    data: ResetSessionResponseData
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_result(cls, result: SessionResetResult) -> ResetSessionResponse:
        return cls(
            trace_id=result.trace_id,
            session_id=result.session_id,
            data=ResetSessionResponseData(
                reset=result.reset,
                message=result.message,
            ),
            metadata=dict(result.metadata),
        )


class HealthResponse(BaseModel):
    """Frontend-safe health response DTO."""

    status: str
    trace_id: str | None = None
    service: str | None = None
    version: str | None = None
    environment: str | None = None
    backend: dict[str, Any] = Field(default_factory=dict)
    api: dict[str, Any] = Field(default_factory=dict)
    workflow_state: dict[str, Any] = Field(default_factory=dict)
    trace: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    llm: dict[str, Any] = Field(default_factory=dict)
    mcp: dict[str, Any] = Field(default_factory=dict)
    checks: dict[str, Any] = Field(default_factory=dict)


class UseCaseCapability(BaseModel):
    """Frontend-safe description of one logical use case."""

    name: str
    display_name: str
    description: str | None = None


class ChatCapabilities(BaseModel):
    """Frontend-safe chat capability flags."""

    enabled: bool
    streaming_enabled: bool
    max_message_chars: int


class SessionCapabilities(BaseModel):
    """Frontend-safe session capability flags."""

    reset_enabled: bool
    history_enabled: bool = False
    client_session_id_enabled: bool


class DebugCapabilities(BaseModel):
    """Frontend-safe debug-route capability flags."""

    trace_routes_enabled: bool


class CapabilitiesResponseData(BaseModel):
    """Frontend-safe capabilities response payload."""

    chat: ChatCapabilities
    sessions: SessionCapabilities
    usecases: list[UseCaseCapability] = Field(default_factory=list)
    debug: DebugCapabilities


class CapabilitiesResponse(BaseModel):
    """Stable public response envelope for backend capabilities."""

    schema_version: str = SCHEMA_VERSION
    trace_id: str | None = None
    data: CapabilitiesResponseData
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApiErrorDetail(BaseModel):
    """Stable error payload content."""

    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ApiErrorResponse(BaseModel):
    """Stable public error envelope for API failures."""

    schema_version: str = SCHEMA_VERSION
    trace_id: str
    error: ApiErrorDetail


def orchestration_result_to_chat_result(
    result: OrchestrationResult,
    *,
    trace_id: str,
) -> SessionChatResult:
    """Map the canonical orchestration result into the API/session boundary model."""

    return SessionChatResult(
        answer=result.answer,
        session_id=result.session_id,
        trace_id=result.trace_id or trace_id,
        agent_name=result.agent_name,
        strategy_name=result.strategy_name,
        llm_profile=result.llm_profile,
        tool_calls=[dict(item) for item in result.tool_calls],
        memory_updates=[dict(item) for item in result.memory_updates],
        metadata=dict(result.metadata),
    )


def _validate_metadata(value: dict[str, Any]) -> None:
    for key in value:
        normalized_key = str(key).strip().lower()
        if is_sensitive_key(normalized_key, sensitive_key_parts=SENSITIVE_KEY_PARTS):
            raise ValueError(f"metadata must not include sensitive key: {key}")

    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    except TypeError as exc:
        raise ValueError("metadata must be JSON-serializable") from exc

    if len(encoded.encode("utf-8")) > _DEFAULT_MAX_METADATA_BYTES:
        raise ValueError("metadata exceeds the default size limit")
