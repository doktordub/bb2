"""Strict Pydantic models for backend runtime configuration."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.state import (
    WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE,
    WORKFLOW_STATE_RESET_MODES,
)

_ALLOWED_SQLITE_SYNCHRONOUS_MODES = frozenset({"NORMAL", "FULL"})
_ALLOWED_TRACE_CAPTURE_MODES = frozenset({"none", "summaries_only"})
_ALLOWED_CORS_ORIGIN_SCHEMES = frozenset({"http", "https"})
_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_HTTP_METHOD_PATTERN = re.compile(r"^[A-Z]+$")


class StrictConfigModel(BaseModel):
    """Base model for strict configuration parsing."""

    model_config = ConfigDict(extra="forbid")


class AppConfig(StrictConfigModel):
    name: str
    environment: str = "local"
    active_usecase: str
    data_dir: str = "./data"


class FeatureConfig(StrictConfigModel):
    streaming_enabled: bool = True
    memory_enabled: bool = True
    tools_enabled: bool = True
    trace_enabled: bool = True


class UseCaseMemoryConfig(StrictConfigModel):
    enabled: bool = True
    include_document_chunks: bool = True
    default_limit: int = Field(default=10, ge=1, le=100)


class UseCaseToolConfig(StrictConfigModel):
    enabled: bool = True
    allowed_tools: list[str] = Field(default_factory=list)


class UseCaseConfig(StrictConfigModel):
    enabled: bool = True
    description: str | None = None
    strategy: str
    default_agent: str
    allowed_agents: list[str]
    orchestrator_llm_profile: str | None = None
    memory: UseCaseMemoryConfig = Field(default_factory=UseCaseMemoryConfig)
    tools: UseCaseToolConfig = Field(default_factory=UseCaseToolConfig)
    policy_profile: str = "default"


class StrategyConfig(StrictConfigModel):
    enabled: bool = True
    type: str
    description: str | None = None
    llm_profile: str | None = None
    max_candidate_agents: int | None = Field(default=None, ge=1, le=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentMemoryConfig(StrictConfigModel):
    search_enabled: bool = True
    write_enabled: bool = False


class AgentPromptConfig(StrictConfigModel):
    system_prompt: str | None = None
    developer_prompt: str | None = None


class AgentConfig(StrictConfigModel):
    enabled: bool = True
    module: str
    class_name: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    llm_profile: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    memory: AgentMemoryConfig = Field(default_factory=AgentMemoryConfig)
    prompts: AgentPromptConfig = Field(default_factory=AgentPromptConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMProviderConfig(StrictConfigModel):
    type: str
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    default_headers: dict[str, str] = Field(default_factory=dict)


class LLMProfileConfig(StrictConfigModel):
    provider: str
    model: str
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    fallback_profiles: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMConfig(StrictConfigModel):
    default_profile: str
    providers: dict[str, LLMProviderConfig]
    profiles: dict[str, LLMProfileConfig]


class MCPServerConfig(StrictConfigModel):
    url: str
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    tool_discovery_enabled: bool = True


class MCPConfig(StrictConfigModel):
    main: MCPServerConfig


class SqliteStoreConfig(StrictConfigModel):
    path: str | None = None
    create_parent_dirs: bool = True
    initialize_schema: bool = True
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    busy_timeout_ms: int = Field(default=5000, ge=0)
    foreign_keys: bool = True
    required: bool = True

    @field_validator("journal_mode")
    @classmethod
    def normalize_journal_mode(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized == "":
            raise ValueError("journal_mode must not be empty")
        return normalized

    @field_validator("synchronous")
    @classmethod
    def normalize_synchronous(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in _ALLOWED_SQLITE_SYNCHRONOUS_MODES:
            supported = ", ".join(sorted(_ALLOWED_SQLITE_SYNCHRONOUS_MODES))
            raise ValueError(f"synchronous must be one of: {supported}")
        return normalized


class WorkflowStateSqliteConfig(SqliteStoreConfig):
    max_state_bytes: int = Field(default=1048576, ge=1)
    max_history_messages: int = Field(default=50, ge=1)
    reset_mode: str = WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE
    store_user_id: bool = False
    store_user_id_hash: bool = True

    @field_validator("reset_mode")
    @classmethod
    def normalize_reset_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in WORKFLOW_STATE_RESET_MODES:
            supported = ", ".join(sorted(WORKFLOW_STATE_RESET_MODES))
            raise ValueError(f"reset_mode must be one of: {supported}")
        return normalized


class TraceRetentionConfig(StrictConfigModel):
    enabled: bool = False
    keep_days: int = Field(default=30, ge=1)
    cleanup_batch_size: int = Field(default=1000, ge=1)


class TraceSqliteConfig(SqliteStoreConfig):
    max_event_payload_bytes: int | None = Field(default=None, ge=1)
    payload_max_chars: int | None = Field(default=None, ge=1)
    max_error_detail_bytes: int = Field(default=4096, ge=1)
    max_events_per_trace_read: int = Field(default=1000, ge=1)
    max_search_results: int = Field(default=200, ge=1)
    store_raw_session_id: bool = False
    store_session_id_hash: bool = True
    store_raw_user_id: bool = False
    store_user_id_hash: bool = True
    capture_request_body: bool = False
    capture_response_body: bool = False
    capture_llm_prompts: bool = False
    capture_llm_completions: bool = False
    capture_tool_payloads: str = "summaries_only"
    capture_memory_queries: str = "summaries_only"
    retention: TraceRetentionConfig = Field(default_factory=TraceRetentionConfig)

    @field_validator("capture_tool_payloads", "capture_memory_queries")
    @classmethod
    def normalize_capture_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_TRACE_CAPTURE_MODES:
            supported = ", ".join(sorted(_ALLOWED_TRACE_CAPTURE_MODES))
            raise ValueError(f"capture mode must be one of: {supported}")
        return normalized


class MemoryStoreProviderConfig(StrictConfigModel):
    config_path: str | None = None
    database_path: str | None = None
    default_scope: str = "project"
    search_limit_default: int = Field(default=10, ge=1, le=100)
    search_limit_max: int = Field(default=30, ge=1, le=100)
    allow_writes: bool = False


class StoreConfig(StrictConfigModel):
    provider: str
    path: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    required: bool | None = None
    sqlite: SqliteStoreConfig | None = None
    memory_store: MemoryStoreProviderConfig | None = None


class WorkflowStateStoreConfig(StoreConfig):
    sqlite: WorkflowStateSqliteConfig | None = None


class TraceStoreConfig(StoreConfig):
    sqlite: TraceSqliteConfig | None = None


class PersistenceConfig(StrictConfigModel):
    base_dir: str = "./data"
    workflow_state: WorkflowStateStoreConfig
    trace: TraceStoreConfig
    memory: StoreConfig


class PolicyProfileConfig(StrictConfigModel):
    deny_unknown_tools: bool = True
    deny_unknown_llm_profiles: bool = True
    require_memory_scope: bool = True
    allow_memory_writes: bool = False


class PolicyConfig(StrictConfigModel):
    default_profile: str = "default"
    profiles: dict[str, PolicyProfileConfig]


class ObservabilityConfig(StrictConfigModel):
    log_level: str = "INFO"
    structured_logging: bool = True
    trace_enabled: bool = True
    trace_payloads_enabled: bool = True
    trace_store_required: bool = True
    redact_secrets: bool = True
    include_stack_traces_in_logs: bool = False
    include_stack_traces_in_traces: bool = False
    max_trace_payload_chars: int = Field(default=8000, ge=1)
    slow_request_ms: int = Field(default=5000, ge=0)
    slow_llm_call_ms: int = Field(default=30000, ge=0)
    slow_tool_call_ms: int = Field(default=10000, ge=0)
    metrics_enabled: bool = True


class HealthConfig(StrictConfigModel):
    expose_config_summary: bool = True
    expose_provider_names: bool = True
    expose_secret_values: bool = False
    include_component_details: bool = True


class ApiCorsConfig(StrictConfigModel):
    enabled: bool = False
    allow_origins: list[str] = Field(default_factory=list)
    allow_credentials: bool = True
    allow_methods: list[str] = Field(
        default_factory=lambda: ["GET", "POST", "OPTIONS"]
    )
    allow_headers: list[str] = Field(
        default_factory=lambda: [
            "Authorization",
            "Content-Type",
            "X-Request-Id",
            "X-Trace-Id",
        ]
    )

    @field_validator("allow_origins")
    @classmethod
    def normalize_allow_origins(cls, value: list[str]) -> list[str]:
        return [_normalize_cors_origin(item) for item in value]

    @field_validator("allow_methods")
    @classmethod
    def normalize_allow_methods(cls, value: list[str]) -> list[str]:
        return [_normalize_http_method(item) for item in value]

    @field_validator("allow_headers")
    @classmethod
    def normalize_allow_headers(cls, value: list[str]) -> list[str]:
        return [_normalize_header_name(item, field_name="allow_headers") for item in value]

    @model_validator(mode="after")
    def validate_enabled_cors(self) -> ApiCorsConfig:
        if not self.enabled:
            return self

        if not self.allow_origins:
            raise ValueError("allow_origins must not be empty when CORS is enabled")

        if not self.allow_methods:
            raise ValueError("allow_methods must not be empty when CORS is enabled")

        if not self.allow_headers:
            raise ValueError("allow_headers must not be empty when CORS is enabled")

        return self


class ApiRequestLimitsConfig(StrictConfigModel):
    max_body_bytes: int = Field(default=1048576, ge=1)
    max_message_chars: int = Field(default=20000, ge=1)
    max_metadata_bytes: int = Field(default=65536, ge=1)
    request_timeout_seconds: int = Field(default=120, ge=1)
    stream_timeout_seconds: int = Field(default=300, ge=1)

    @model_validator(mode="after")
    def validate_timeout_order(self) -> ApiRequestLimitsConfig:
        if self.stream_timeout_seconds < self.request_timeout_seconds:
            raise ValueError(
                "stream_timeout_seconds must be greater than or equal to "
                "request_timeout_seconds"
            )
        return self


class ApiSessionsConfig(StrictConfigModel):
    accept_client_session_id: bool = True
    create_session_when_missing: bool = True
    session_id_header: str = "X-Session-Id"

    @field_validator("session_id_header")
    @classmethod
    def normalize_session_id_header(cls, value: str) -> str:
        return _normalize_header_name(value, field_name="session_id_header")


class ApiTracingConfig(StrictConfigModel):
    accept_client_trace_id: bool = True
    response_trace_header: str = "X-Trace-Id"
    record_request_received: bool = True
    record_response_returned: bool = True
    record_validation_errors: bool = True

    @field_validator("response_trace_header")
    @classmethod
    def normalize_response_trace_header(cls, value: str) -> str:
        return _normalize_header_name(value, field_name="response_trace_header")


class ApiDebugRoutesConfig(StrictConfigModel):
    enabled: bool = False
    require_localhost: bool = True
    max_trace_events: int = Field(default=500, ge=1)
    max_search_results: int = Field(default=50, ge=1)


class ApiSseConfig(StrictConfigModel):
    heartbeat_seconds: int = Field(default=15, ge=1)
    send_trace_id_event: bool = True
    send_metadata_events: bool = True


class ApiConfig(StrictConfigModel):
    enabled: bool = True
    base_path: str = ""
    docs_enabled: bool = True
    openapi_enabled: bool = True
    cors: ApiCorsConfig = Field(default_factory=ApiCorsConfig)
    request_limits: ApiRequestLimitsConfig = Field(default_factory=ApiRequestLimitsConfig)
    sessions: ApiSessionsConfig = Field(default_factory=ApiSessionsConfig)
    tracing: ApiTracingConfig = Field(default_factory=ApiTracingConfig)
    debug_routes: ApiDebugRoutesConfig = Field(default_factory=ApiDebugRoutesConfig)
    sse: ApiSseConfig = Field(default_factory=ApiSseConfig)

    @field_validator("base_path")
    @classmethod
    def normalize_base_path(cls, value: str) -> str:
        normalized = value.strip()
        if normalized in {"", "/"}:
            return ""

        if not normalized.startswith("/"):
            raise ValueError("base_path must start with '/' or be empty")

        if normalized.endswith("/"):
            normalized = normalized[:-1]

        if "//" in normalized:
            raise ValueError("base_path must not contain empty path segments")

        return normalized

    @model_validator(mode="after")
    def validate_docs_settings(self) -> ApiConfig:
        if self.docs_enabled and not self.openapi_enabled:
            raise ValueError("docs_enabled requires openapi_enabled to be true")
        return self


class BackendConfig(StrictConfigModel):
    app: AppConfig
    api: ApiConfig = Field(default_factory=ApiConfig)
    features: FeatureConfig = Field(default_factory=FeatureConfig)
    usecases: dict[str, UseCaseConfig]
    strategies: dict[str, StrategyConfig]
    agents: dict[str, AgentConfig]
    llm: LLMConfig
    mcp: MCPConfig
    persistence: PersistenceConfig
    policy: PolicyConfig
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)


def _normalize_cors_origin(value: str) -> str:
    normalized = value.strip()
    if normalized == "*":
        return normalized

    parsed = urlsplit(normalized)
    if parsed.scheme not in _ALLOWED_CORS_ORIGIN_SCHEMES or parsed.netloc == "":
        raise ValueError("allow_origins entries must be http(s) origins or '*'")

    if parsed.query or parsed.fragment:
        raise ValueError("allow_origins entries must not include query or fragment components")

    if parsed.path not in {"", "/"}:
        raise ValueError("allow_origins entries must not include a path component")

    return f"{parsed.scheme}://{parsed.netloc}"


def _normalize_http_method(value: str) -> str:
    normalized = value.strip().upper()
    if not _HTTP_METHOD_PATTERN.fullmatch(normalized):
        raise ValueError("allow_methods entries must be valid uppercase HTTP methods")
    return normalized


def _normalize_header_name(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if normalized == "*":
        return normalized

    if not _HEADER_NAME_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a valid HTTP header name")

    return normalized