"""API request and response DTOs for the backend boundary."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.contracts.results import OrchestrationResult
from app.deployment.process_control import RestartRequestReceipt
from app.observability.redaction import SENSITIVE_KEY_PARTS, is_sensitive_key
from app.session.mapping import build_visualization_response_metadata
from app.session.models import (
    SessionChatResult,
    SessionDeleteResult,
    SessionHistoryResult,
    SessionListResult,
    SessionResetResult,
)
from app.visualization.models import ChartArtifact, ChartComputedFacts, ChartDataSlice

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
    artifacts: list[ChartArtifact] = Field(default_factory=list)


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
                artifacts=[ChartArtifact.model_validate(dict(item)) for item in result.artifacts],
            ),
            metadata=dict(result.metadata),
        )


class ArtifactResponse(BaseModel):
    """Stable public response envelope for one visualization artifact retrieval."""

    schema_version: str = SCHEMA_VERSION
    trace_id: str
    session_id: str
    data: ChartArtifact | ChartDataSlice | ChartComputedFacts
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class SessionHistoryMessageData(BaseModel):
    """Frontend-safe message projection for session history."""

    role: str
    content: str
    created_at: str | None = None
    artifacts: list[ChartArtifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionHistoryResponseData(BaseModel):
    """Response body for session history."""

    messages: list[SessionHistoryMessageData] = Field(default_factory=list)
    truncated: bool


class SessionHistoryResponse(BaseModel):
    """Stable public response envelope for session history."""

    schema_version: str = SCHEMA_VERSION
    trace_id: str
    session_id: str
    data: SessionHistoryResponseData
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_result(cls, result: SessionHistoryResult) -> SessionHistoryResponse:
        return cls(
            trace_id=result.trace_id,
            session_id=result.session_id,
            data=SessionHistoryResponseData(
                messages=[
                    SessionHistoryMessageData(
                        role=item.role,
                        content=item.content,
                        created_at=item.created_at,
                        artifacts=[ChartArtifact.model_validate(dict(artifact)) for artifact in item.artifacts],
                        metadata=dict(item.metadata),
                    )
                    for item in result.messages
                ],
                truncated=result.truncated,
            ),
            metadata=dict(result.metadata),
        )


class SessionSummaryData(BaseModel):
    """Frontend-safe session summary DTO."""

    session_id: str
    usecase: str | None = None
    status: str
    created_at: str | None = None
    updated_at: str | None = None
    last_activity_at: str | None = None
    reset_count: int
    message_count: int


class SessionListResponseData(BaseModel):
    """Response body for session listing."""

    sessions: list[SessionSummaryData] = Field(default_factory=list)
    limit: int
    has_more: bool


class SessionListResponse(BaseModel):
    """Stable public response envelope for session listing."""

    schema_version: str = SCHEMA_VERSION
    trace_id: str
    data: SessionListResponseData
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_result(cls, result: SessionListResult) -> SessionListResponse:
        return cls(
            trace_id=result.trace_id,
            data=SessionListResponseData(
                sessions=[
                    SessionSummaryData(
                        session_id=item.session_id,
                        usecase=item.usecase,
                        status=item.status,
                        created_at=item.created_at,
                        updated_at=item.updated_at,
                        last_activity_at=item.last_activity_at,
                        reset_count=item.reset_count,
                        message_count=item.message_count,
                    )
                    for item in result.sessions
                ],
                limit=result.limit,
                has_more=result.has_more,
            ),
            metadata=dict(result.metadata),
        )


class SessionDeleteResponseData(BaseModel):
    """Response body for session deletion."""

    deleted: bool
    message: str


class SessionDeleteResponse(BaseModel):
    """Stable public response envelope for session deletion."""

    schema_version: str = SCHEMA_VERSION
    trace_id: str
    session_id: str
    data: SessionDeleteResponseData
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_result(cls, result: SessionDeleteResult) -> SessionDeleteResponse:
        return cls(
            trace_id=result.trace_id,
            session_id=result.session_id,
            data=SessionDeleteResponseData(
                deleted=result.deleted,
                message=result.message,
            ),
            metadata=dict(result.metadata),
        )


class RestartResponseData(BaseModel):
    """Response body for accepted restart requests."""

    restart_requested: bool
    request_id: str
    requested_at: str
    signal_path: str


class RestartResponse(BaseModel):
    """Stable public response envelope for backend restart requests."""

    schema_version: str = SCHEMA_VERSION
    trace_id: str
    data: RestartResponseData
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_receipt(
        cls,
        *,
        trace_id: str,
        receipt: RestartRequestReceipt,
    ) -> RestartResponse:
        return cls(
            trace_id=trace_id,
            data=RestartResponseData(
                restart_requested=receipt.restart_requested,
                request_id=receipt.request_id,
                requested_at=receipt.requested_at,
                signal_path=receipt.signal_path,
            ),
            metadata=dict(receipt.metadata),
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
    visualization: dict[str, Any] = Field(default_factory=dict)
    workflow_state: dict[str, Any] = Field(default_factory=dict)
    trace: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    llm: dict[str, Any] = Field(default_factory=dict)
    mcp: dict[str, Any] = Field(default_factory=dict)
    orchestration: dict[str, Any] = Field(default_factory=dict)
    checks: dict[str, Any] = Field(default_factory=dict)


class UseCaseCapability(BaseModel):
    """Frontend-safe description of one logical use case."""

    name: str
    display_name: str
    description: str | None = None
    strategy_type: str
    streaming_supported: bool
    memory_enabled: bool
    tools_enabled: bool


class ChatCapabilities(BaseModel):
    """Frontend-safe chat capability flags."""

    enabled: bool
    streaming_enabled: bool
    max_message_chars: int


class SessionCapabilities(BaseModel):
    """Frontend-safe session capability flags."""

    reset_enabled: bool
    history_enabled: bool = False
    list_enabled: bool = False
    delete_enabled: bool = False
    client_session_id_enabled: bool
    continuity_enabled: bool = False
    continuity_mode: str = "disabled"
    summary_compaction_enabled: bool = False


class DebugCapabilities(BaseModel):
    """Frontend-safe debug-route capability flags."""

    trace_routes_enabled: bool
    restart_enabled: bool = False


class MemoryCapabilities(BaseModel):
    """Frontend-safe memory capability flags."""

    enabled: bool
    configured: bool
    provider: str | None = None
    search_available: bool
    ingest_available: bool


class ToolingCapabilities(BaseModel):
    """Frontend-safe tool-gateway capability flags."""

    enabled: bool
    configured: bool
    streaming_supported: bool
    total_tools: int
    approval_required_tools: int
    safety_levels: dict[str, int] = Field(default_factory=dict)
    transport: str | None = None
    discovery_enabled: bool | None = None


class LLMCapabilities(BaseModel):
    """Frontend-safe LLM capability flags."""

    enabled: bool
    default_profile: str | None = None
    streaming_supported: bool
    structured_output_supported: bool


class VisualizationCapabilities(BaseModel):
    """Frontend-safe visualization capability flags."""

    enabled: bool
    default_renderer: str | None = None
    allowed_renderers: list[str] = Field(default_factory=list)
    spec_version: str | None = None
    context_summary_mode: str = "disabled"
    supported_chart_types: list[str] = Field(default_factory=list)
    reference_mode_supported: bool = False
    reference_mode_enabled: bool = False
    artifact_store_enabled: bool = False
    artifact_store_provider: str | None = None
    durable_replay_enabled: bool = False
    exact_followup_retrieval_enabled: bool = False
    limits: dict[str, Any] = Field(default_factory=dict)


class AgentCapabilities(BaseModel):
    """Frontend-safe agent descriptor surfaced through capabilities."""

    name: str
    display_name: str
    type: str
    streaming_supported: bool
    capabilities: list[str] = Field(default_factory=list)


class CapabilitiesResponseData(BaseModel):
    """Frontend-safe capabilities response payload."""

    chat: ChatCapabilities
    sessions: SessionCapabilities
    usecases: list[UseCaseCapability] = Field(default_factory=list)
    agents: list[AgentCapabilities] = Field(default_factory=list)
    debug: DebugCapabilities
    tools: ToolingCapabilities
    memory: MemoryCapabilities
    llm: LLMCapabilities
    visualization: VisualizationCapabilities


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

    artifacts = [item.model_dump(mode="python") for item in result.artifacts]
    context_contributions = [
        item.model_dump(mode="python") for item in result.context_contributions
    ]
    return SessionChatResult(
        answer=result.answer,
        session_id=result.session_id,
        trace_id=result.trace_id or trace_id,
        agent_name=result.agent_name,
        strategy_name=result.strategy_name,
        llm_profile=result.llm_profile,
        tool_calls=[dict(item) for item in result.tool_calls],
        memory_updates=[dict(item) for item in result.memory_updates],
        artifacts=artifacts,
        metadata=build_visualization_response_metadata(
            artifacts=artifacts,
            context_contributions=context_contributions,
        ),
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
