"""Immutable validated configuration view."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal, cast

from app.config.redaction import redact_config
from app.contracts.config import ConfigurationView
from app.contracts.errors import ConfigurationError
from app.observability.redaction import Redactor
from app.policy.settings import (
    PolicyApprovalSettings,
    PolicyAuditSettings,
    PolicyCapabilitySettings,
    PolicyDecisionCacheSettings,
    PolicyFallbackSettings,
    PolicyHealthSettings,
    PolicyLLMSettings,
    PolicyMemorySettings,
    PolicyNamedAccessSettings,
    PolicyProfileSettings,
    PolicySettings,
    PolicyStreamSettings,
    PolicyToolSettings,
    PolicyTraceSettings,
)
from app.persistence.paths import resolve_backend_path, resolve_data_path
from app.persistence.settings import get_persistence_settings

if TYPE_CHECKING:
    from app.persistence.settings import PersistenceSettings


@dataclass(frozen=True, slots=True)
class ObservabilitySettings:
    """Typed observability settings resolved from validated configuration."""

    log_level: str
    structured_logging: bool
    trace_enabled: bool
    trace_payloads_enabled: bool
    trace_store_required: bool
    redact_secrets: bool
    include_stack_traces_in_logs: bool
    include_stack_traces_in_traces: bool
    max_trace_payload_chars: int
    slow_request_ms: int
    slow_llm_call_ms: int
    slow_tool_call_ms: int
    metrics_enabled: bool


@dataclass(frozen=True, slots=True)
class HealthSettings:
    """Typed health settings resolved from validated configuration."""

    expose_config_summary: bool
    expose_provider_names: bool
    expose_secret_values: bool
    include_component_details: bool


@dataclass(frozen=True, slots=True)
class DeploymentMetricsSettings:
    """Typed deployment metrics settings resolved from validated configuration."""

    enabled: bool
    bind_host: str
    port: int


@dataclass(frozen=True, slots=True)
class DeploymentReadinessSettings:
    """Typed deployment readiness settings resolved from validated configuration."""

    enabled: bool
    bind_host: str | None
    port: int | None


@dataclass(frozen=True, slots=True)
class DeploymentSettings:
    """Typed deployment settings resolved from validated configuration."""

    profile: str
    host: str
    port: int
    public_base_url: str | None
    log_dir: Path
    runtime_dir: Path
    graceful_shutdown_seconds: int
    metrics: DeploymentMetricsSettings
    readiness: DeploymentReadinessSettings


@dataclass(frozen=True, slots=True)
class CorsSettings:
    """Typed API CORS settings resolved from validated configuration."""

    enabled: bool
    allow_origins: tuple[str, ...]
    allow_credentials: bool
    allow_methods: tuple[str, ...]
    allow_headers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApiRequestLimitSettings:
    """Typed API request limits resolved from validated configuration."""

    max_body_bytes: int
    max_message_chars: int
    max_metadata_bytes: int
    request_timeout_seconds: int
    stream_timeout_seconds: int


@dataclass(frozen=True, slots=True)
class ApiSessionSettings:
    """Typed API session settings resolved from validated configuration."""

    accept_client_session_id: bool
    create_session_when_missing: bool
    session_id_header: str


@dataclass(frozen=True, slots=True)
class ApiTracingSettings:
    """Typed API tracing settings resolved from validated configuration."""

    accept_client_trace_id: bool
    response_trace_header: str
    record_request_received: bool
    record_response_returned: bool
    record_validation_errors: bool


@dataclass(frozen=True, slots=True)
class ApiDebugRoutesSettings:
    """Typed API debug-route settings resolved from validated configuration."""

    enabled: bool
    require_localhost: bool
    restart_enabled: bool
    max_trace_events: int
    max_search_results: int


@dataclass(frozen=True, slots=True)
class ApiSseSettings:
    """Typed API SSE settings resolved from validated configuration."""

    heartbeat_seconds: int
    send_trace_id_event: bool
    send_metadata_events: bool


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Typed API settings resolved from validated configuration."""

    enabled: bool
    base_path: str
    docs_enabled: bool
    openapi_enabled: bool
    cors: CorsSettings
    request_limits: ApiRequestLimitSettings
    sessions: ApiSessionSettings
    tracing: ApiTracingSettings
    debug_routes: ApiDebugRoutesSettings
    sse: ApiSseSettings


@dataclass(frozen=True, slots=True)
class SessionIdentifierSettings:
    """Typed session identifier settings resolved from validated configuration."""

    prefix: str
    accept_client_session_id: bool
    generate_when_missing: bool
    max_length: int
    allowed_pattern: str


@dataclass(frozen=True, slots=True)
class SessionDefaultsSettings:
    """Typed session default settings resolved from validated configuration."""

    default_user_id: str
    default_usecase: str
    default_history_limit: int
    max_history_limit: int
    timezone_metadata_key: str


@dataclass(frozen=True, slots=True)
class SessionLifecycleSettings:
    """Typed session lifecycle settings resolved from validated configuration."""

    create_on_first_chat: bool
    resume_existing_sessions: bool
    reject_unknown_client_session_id: bool
    update_last_seen_on_load: bool
    save_after_failed_orchestration: bool
    save_after_cancelled_stream: bool


@dataclass(frozen=True, slots=True)
class SessionConcurrencySettings:
    """Typed session concurrency settings resolved from validated configuration."""

    mode: str
    conflict_policy: str
    max_retries: int


@dataclass(frozen=True, slots=True)
class SessionStateSettings:
    """Typed session state save settings resolved from validated configuration."""

    save_on_chat_completion: bool
    save_on_stream_completion: bool
    save_on_stream_cancellation: bool
    save_on_stream_failure: bool
    save_each_stream_delta: bool


@dataclass(frozen=True, slots=True)
class SessionHistorySettings:
    """Typed session history settings resolved from validated configuration."""

    enabled: bool
    include_tool_summaries: bool
    include_system_messages: bool
    include_metadata: bool
    max_message_chars: int
    redaction_enabled: bool


@dataclass(frozen=True, slots=True)
class SessionManagementSettings:
    """Typed session admin settings resolved from validated configuration."""

    list_enabled: bool = False
    delete_enabled: bool = False
    default_list_limit: int = 50
    max_list_limit: int = 200


@dataclass(frozen=True, slots=True)
class SessionTracingSettings:
    """Typed session tracing settings resolved from validated configuration."""

    record_session_created: bool
    record_session_resumed: bool
    record_session_reset: bool
    record_state_loaded: bool
    record_state_saved: bool
    record_history_returned: bool
    record_stream_lifecycle: bool


@dataclass(frozen=True, slots=True)
class SessionSettings:
    """Typed session settings resolved from validated configuration."""

    enabled: bool
    identifiers: SessionIdentifierSettings
    defaults: SessionDefaultsSettings
    lifecycle: SessionLifecycleSettings
    concurrency: SessionConcurrencySettings
    state: SessionStateSettings
    history: SessionHistorySettings
    tracing: SessionTracingSettings
    management: SessionManagementSettings = field(default_factory=SessionManagementSettings)


StrategyType = Literal[
    "echo",
    "direct_agent",
    "retrieval_augmented",
    "tool_assisted",
    "router",
    "bounded_planner",
    "memory_update",
    "fallback_answer",
]

AgentType = Literal[
    "general_assistant",
    "document_qa",
    "tool_using",
    "project_agent",
    "memory_curator",
    "reviewer",
    "custom",
]


@dataclass(frozen=True, slots=True)
class ConversationContextSettings:
    """Typed same-session continuity settings resolved from validated config."""

    enabled: bool
    mode: str
    max_messages: int
    max_chars: int
    include_assistant_messages: bool
    summary_threshold_messages: int
    summary_max_chars: int


@dataclass(frozen=True, slots=True)
class OrchestrationDefaultsSettings:
    """Typed orchestration default settings resolved from validated configuration."""

    strategy: str
    fallback_strategy: str
    max_steps: int
    max_tool_calls: int
    max_memory_searches: int
    max_memory_writes: int
    max_llm_calls: int
    max_tool_loop_iterations: int
    max_context_bytes: int
    max_turn_duration_seconds: int
    max_stream_duration_seconds: int
    emit_step_events: bool
    emit_tool_events: bool
    emit_memory_events: bool
    stream_strategy_events: bool
    expose_strategy_metadata: bool
    expose_chain_of_thought: bool
    save_runtime_snapshots: bool
    conversation_context: ConversationContextSettings


@dataclass(frozen=True, slots=True)
class OrchestrationStrategyMemorySettings:
    """Typed strategy memory settings resolved from validated configuration."""

    default_limit: int
    include_document_chunks: bool
    include_user_memory: bool
    min_score: float | None
    max_context_items: int | None
    max_context_bytes: int | None


@dataclass(frozen=True, slots=True)
class OrchestrationStrategyToolSettings:
    """Typed strategy tool settings resolved from validated configuration."""

    max_calls: int | None
    max_tool_loop_iterations: int | None
    allowed_safety_levels: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    stream_tool_events: bool


@dataclass(frozen=True, slots=True)
class OrchestrationUseCaseMemorySettings:
    """Typed use-case memory settings resolved from validated configuration."""

    enabled: bool
    include_document_chunks: bool
    default_limit: int
    allowed_project_ids: tuple[str, ...]
    default_project_id: str | None


@dataclass(frozen=True, slots=True)
class AgentMemorySettings:
    """Typed agent memory settings resolved from validated configuration."""

    search_enabled: bool
    write_enabled: bool
    allowed_project_ids: tuple[str, ...]
    default_project_id: str | None


@dataclass(frozen=True, slots=True)
class OrchestrationUseCaseToolSettings:
    """Typed use-case tool settings resolved from validated configuration."""

    enabled: bool
    allowed_tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategySettings:
    """Typed orchestration strategy settings resolved from validated configuration."""

    name: str
    enabled: bool
    type: StrategyType
    description: str | None
    default_agent: str | None
    allowed_usecases: tuple[str, ...]
    llm_profile: str | None
    planner_llm_profile: str | None
    executor_llm_profile: str | None
    memory_enabled: bool
    memory_write_enabled: bool
    tools_enabled: bool
    max_steps: int | None
    max_tool_calls: int | None
    max_memory_searches: int | None
    max_memory_writes: int | None
    max_llm_calls: int | None
    max_tool_loop_iterations: int | None
    max_context_bytes: int | None
    max_plan_steps: int | None
    max_execute_steps: int | None
    max_candidate_agents: int | None
    candidate_limit: int | None
    candidate_strategies: tuple[str, ...]
    fallback_strategy: str | None
    require_policy_approval: bool
    stream_llm_deltas: bool
    stream_tool_events: bool
    stream_strategy_events: bool | None
    expose_strategy_metadata: bool
    message: str | None
    memory: OrchestrationStrategyMemorySettings
    tools: OrchestrationStrategyToolSettings
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class UseCaseSettings:
    """Typed orchestration use-case settings resolved from validated configuration."""

    name: str
    enabled: bool
    strategy: str
    agent: str | None
    llm_profile: str | None
    display_name: str | None
    description: str | None
    allowed_agents: tuple[str, ...]
    allowed_strategies: tuple[str, ...]
    policy_profile: str
    memory: OrchestrationUseCaseMemorySettings
    tools: OrchestrationUseCaseToolSettings
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OrchestrationSettings:
    """Typed orchestration settings resolved from validated configuration."""

    enabled: bool
    defaults: OrchestrationDefaultsSettings
    strategies: dict[str, StrategySettings]
    usecases: dict[str, UseCaseSettings]


@dataclass(frozen=True, slots=True)
class LLMDefaultsSettings:
    """Typed LLM default settings resolved from validated configuration."""

    profile: str
    timeout_seconds: int
    stream_timeout_seconds: int
    max_retries: int
    trace_prompts: bool
    trace_completions: bool


@dataclass(frozen=True, slots=True)
class LLMProviderSettings:
    """Typed LLM provider settings resolved from validated configuration."""

    name: str
    type: str
    enabled: bool
    base_url: str | None
    endpoint: str | None
    api_key: str | None
    auth_header: str | None
    auth_token: str | None
    timeout_seconds: int
    stream_timeout_seconds: int
    headers: dict[str, str]
    extra: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMProfileAllowlistSettings:
    """Typed LLM profile allowlist settings resolved from validated configuration."""

    usecases: tuple[str, ...]
    agents: tuple[str, ...]
    strategies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LLMProfileSettings:
    """Typed LLM profile settings resolved from validated configuration."""

    name: str
    enabled: bool
    provider: str
    model: str
    temperature: float | None
    top_p: float | None
    max_output_tokens: int | None
    max_input_tokens: int | None
    max_total_tokens: int | None
    timeout_seconds: int | None
    stream_timeout_seconds: int | None
    supports_streaming: bool
    supports_json_schema: bool
    supports_tool_calling: bool
    allowed_for: LLMProfileAllowlistSettings
    fallback_profiles: tuple[str, ...]
    extra: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMSettings:
    """Typed LLM settings resolved from validated configuration."""

    defaults: LLMDefaultsSettings
    providers: dict[str, LLMProviderSettings]
    profiles: dict[str, LLMProfileSettings]


@dataclass(frozen=True, slots=True)
class ToolingDefaultsSettings:
    """Typed tooling defaults resolved from validated configuration."""

    timeout_seconds: int
    stream_timeout_seconds: int
    max_retries: int
    max_argument_bytes: int
    max_result_bytes: int
    trace_arguments: bool
    trace_results: bool
    discovery_on_startup: bool
    discovery_refresh_seconds: int


@dataclass(frozen=True, slots=True)
class MCPAuthSettings:
    """Typed MCP auth settings resolved from validated configuration."""

    mode: Literal["none", "bearer", "jwt", "oauth_client_credentials"]
    token: str | None
    jwt: str | None
    token_url: str | None
    client_id: str | None
    client_secret: str | None
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MCPServerSettings:
    """Typed MCP server settings resolved from validated configuration."""

    name: str
    enabled: bool
    endpoint: str | None
    transport: Literal["http", "sse", "websocket"]
    timeout_seconds: int
    stream_timeout_seconds: int
    auth: MCPAuthSettings
    tool_discovery_enabled: bool


@dataclass(frozen=True, slots=True)
class ToolAllowedForSettings:
    """Typed logical-tool allowlist settings resolved from validated configuration."""

    usecases: tuple[str, ...]
    agents: tuple[str, ...]
    strategies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ToolDefinitionSettings:
    """Typed logical-tool definition resolved from validated configuration."""

    name: str
    enabled: bool
    mcp_tool_name: str
    description: str | None
    allowed_for: ToolAllowedForSettings
    timeout_seconds: int | None
    max_argument_bytes: int | None
    max_result_bytes: int | None
    approval_required: bool
    input_schema_override: dict[str, Any] | None
    output_schema_override: dict[str, Any] | None
    tags: tuple[str, ...]
    safety_level: Literal["read_only", "write", "destructive", "external_side_effect"]
    extra: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolRegistrySettings:
    """Typed tool-registry settings resolved from validated configuration."""

    allow_discovered_tools: bool
    require_configured_allowlist: bool
    tools: dict[str, ToolDefinitionSettings]


@dataclass(frozen=True, slots=True)
class ToolingSettings:
    """Typed tooling settings resolved from validated configuration."""

    enabled: bool
    defaults: ToolingDefaultsSettings
    mcp_server: MCPServerSettings
    registry: ToolRegistrySettings


@dataclass(frozen=True, slots=True)
class MemoryDefaultsSettings:
    """Typed memory defaults resolved from validated configuration."""

    default_scope: str
    top_k: int
    include_agent_memories: bool
    include_document_chunks: bool
    include_graph_context: bool
    max_result_chars: int
    max_total_context_chars: int
    trace_query_capture: str
    trace_result_content_capture: str


@dataclass(frozen=True, slots=True)
class MemoryStoreDatabaseSettings:
    """Typed memory-store database settings resolved from validated configuration."""

    path: Path
    create_if_missing: bool
    schema_version: int
    embedded_single_process: bool


@dataclass(frozen=True, slots=True)
class MemoryEmbeddingsSettings:
    """Typed memory-store embeddings settings resolved from validated configuration."""

    provider: str
    model: str
    model_version: str | None
    dimension: int | None
    batch_size: int
    normalize: bool
    dimension_mismatch: str


@dataclass(frozen=True, slots=True)
class MemoryRerankerSettings:
    """Typed memory-store reranker settings resolved from validated configuration."""

    enabled: bool
    provider: str
    model: str
    model_version: str | None
    top_n: int


@dataclass(frozen=True, slots=True)
class MemoryStoreSettings:
    """Typed memory-store adapter settings resolved from validated configuration."""

    config_path: Path | None
    database: MemoryStoreDatabaseSettings
    embeddings: MemoryEmbeddingsSettings
    reranker: MemoryRerankerSettings


@dataclass(frozen=True, slots=True)
class MemoryChunkingSettings:
    """Typed memory chunking settings resolved from validated configuration."""

    strategy: str
    max_tokens: int
    overlap_tokens: int
    include_heading_path: bool
    include_frontmatter_in_embedding: bool
    preserve_code_blocks: bool
    removed_chunk_policy: str


@dataclass(frozen=True, slots=True)
class MemorySearchSettings:
    """Typed memory search settings resolved from validated configuration."""

    limit_max: int
    vector_top_n: int
    fts_top_n: int
    rrf_k: int
    graph_expansion_enabled: bool
    graph_expansion_hops: int
    final_top_k: int
    include_component_scores: bool
    include_debug: bool


@dataclass(frozen=True, slots=True)
class MemoryScoringWeightsSettings:
    """Typed memory scoring weights resolved from validated configuration."""

    reranker: float
    retrieval_fusion: float
    vector: float
    full_text: float
    temporal: float
    importance: float
    confidence: float
    graph: float
    user_rating: float


@dataclass(frozen=True, slots=True)
class MemoryScoringSettings:
    """Typed memory scoring settings resolved from validated configuration."""

    weights: MemoryScoringWeightsSettings


@dataclass(frozen=True, slots=True)
class MemoryLifecycleSettings:
    """Typed memory lifecycle settings resolved from validated configuration."""

    allow_writes: bool
    default_ttl_days: int | None
    contradiction_policy: str
    supersede_policy: str
    require_durable_scope_for_writes: bool
    allow_session_scope_only_writes: bool
    require_durable_scope_for_delete_export: bool


@dataclass(frozen=True, slots=True)
class MemoryPrivacySettings:
    """Typed memory privacy settings resolved from validated configuration."""

    default_sensitivity: str
    allow_llm_context_default: bool
    allow_retrieval_default: bool
    delete_by_scope_requires_confirm: bool
    enable_export_by_scope: bool
    enable_delete_by_scope: bool
    hard_delete_enabled: bool
    tombstone_on_forget: bool
    require_policy_approval_for_delete_export: bool


@dataclass(frozen=True, slots=True)
class MemoryHealthSettings:
    """Typed memory health settings resolved from validated configuration."""

    deep_check_enabled: bool


@dataclass(frozen=True, slots=True)
class MemorySettings:
    """Typed memory settings resolved from validated configuration."""

    enabled: bool
    provider: str
    required: bool
    defaults: MemoryDefaultsSettings
    store: MemoryStoreSettings
    chunking: MemoryChunkingSettings
    search: MemorySearchSettings
    scoring: MemoryScoringSettings
    lifecycle: MemoryLifecycleSettings
    privacy: MemoryPrivacySettings
    health: MemoryHealthSettings


@dataclass(frozen=True, slots=True)
class AgentCapabilitySettings:
    """Typed agent capability settings resolved from validated configuration."""

    answer: bool
    review: bool
    stream: bool
    memory_read: bool
    memory_write: bool
    memory_candidate_extract: bool
    tool_intents: bool
    tool_execute: bool
    self_managed_memory: bool
    self_managed_tools: bool


@dataclass(frozen=True, slots=True)
class AgentLimitSettings:
    """Typed agent execution limits resolved from validated configuration."""

    max_prompt_context_bytes: int
    max_output_chars: int
    max_tool_intents: int
    max_memory_candidates: int
    max_llm_calls: int
    max_self_managed_tool_calls: int
    max_self_managed_memory_searches: int


@dataclass(frozen=True, slots=True)
class AgentContextPolicySettings:
    """Typed agent context policy resolved from validated configuration."""

    require_context_for_grounded_claims: bool
    cite_context_labels: bool
    max_context_items: int
    max_context_bytes: int
    allow_untrusted_context_instructions: bool


@dataclass(frozen=True, slots=True)
class AgentPromptOverrideSettings:
    """Typed per-plugin prompt overrides resolved from validated configuration."""

    system_prompt: str | None
    developer_prompt: str | None


@dataclass(frozen=True, slots=True)
class AgentPluginSettings:
    """Typed agent plugin settings resolved from validated configuration."""

    name: str
    type: AgentType
    enabled: bool
    display_name: str | None
    description: str | None
    llm_profile: str | None
    prompt_profile: str | None
    capabilities: AgentCapabilitySettings
    limits: AgentLimitSettings
    context_policy: AgentContextPolicySettings
    allowed_tool_intents: tuple[str, ...]
    allowed_memory_scopes: tuple[str, ...]
    memory: AgentMemorySettings
    expose_metadata: bool
    stream_llm_deltas: bool
    module: str | None
    class_name: str | None
    prompts: AgentPromptOverrideSettings
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AgentsSettings:
    """Typed agent settings resolved from validated configuration."""

    enabled: bool
    stream_llm_deltas: bool
    expose_agent_metadata: bool
    strict_prompt_profile_validation: bool
    known_prompt_profiles: tuple[str, ...]
    allow_self_managed_tools: bool
    allow_self_managed_memory: bool
    allow_memory_write: bool
    limits: AgentLimitSettings
    context_policy: AgentContextPolicySettings
    plugins: dict[str, AgentPluginSettings]


class ValidatedConfigurationView:
    """Read-only runtime access to validated configuration values."""

    def __init__(self, values: Mapping[str, Any]) -> None:
        self._values = cast(Mapping[str, Any], _freeze(dict(values)))

    def get(self, path: str, default: Any = None) -> Any:
        if path == "":
            return self._values

        current: Any = self._values
        for part in path.split("."):
            if not isinstance(current, Mapping):
                return default
            if part in current:
                current = current[part]
                continue
            compatibility_value = _read_agent_plugin_compatibility_value(current, part)
            if compatibility_value is None:
                return default
            current = compatibility_value
        return current

    def require(self, path: str) -> Any:
        value = self.get(path, None)
        if value is None:
            raise ConfigurationError(f"Missing required config path: {path}")
        return value

    def section(self, path: str) -> dict[str, Any]:
        value = self.require(path)
        if not isinstance(value, Mapping):
            raise ConfigurationError(f"Config path is not a section: {path}")
        return cast(dict[str, Any], _unfreeze(value))

    def observability_settings(self) -> ObservabilitySettings:
        return get_observability_settings(self)

    def health_settings(self) -> HealthSettings:
        return get_health_settings(self)

    def deployment_settings(self) -> DeploymentSettings:
        return get_deployment_settings(self)

    def api_settings(self) -> ApiSettings:
        return get_api_settings(self)

    def session_settings(self) -> SessionSettings:
        return get_session_settings(self)

    def orchestration_settings(self) -> OrchestrationSettings:
        return get_orchestration_settings(self)

    def llm_settings(self) -> LLMSettings:
        return get_llm_settings(self)

    def agents_settings(self) -> AgentsSettings:
        return get_agents_settings(self)

    def tooling_settings(self) -> ToolingSettings:
        return get_tooling_settings(self)

    def memory_settings(self) -> MemorySettings:
        return get_memory_settings(self)

    def persistence_settings(self) -> PersistenceSettings:
        return get_persistence_settings(self)

    def as_redacted_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], redact_config(_unfreeze(self._values)))


def get_observability_settings(config: ConfigurationView) -> ObservabilitySettings:
    """Resolve typed observability settings from validated configuration."""

    return ObservabilitySettings(
        log_level=_read_str(config, "observability.log_level", "INFO"),
        structured_logging=_read_bool(config, "observability.structured_logging", True),
        trace_enabled=_read_bool(config, "observability.trace_enabled", True),
        trace_payloads_enabled=_read_bool(config, "observability.trace_payloads_enabled", True),
        trace_store_required=_read_bool(config, "observability.trace_store_required", True),
        redact_secrets=_read_bool(config, "observability.redact_secrets", True),
        include_stack_traces_in_logs=_read_bool(
            config,
            "observability.include_stack_traces_in_logs",
            False,
        ),
        include_stack_traces_in_traces=_read_bool(
            config,
            "observability.include_stack_traces_in_traces",
            False,
        ),
        max_trace_payload_chars=_read_int(
            config,
            "observability.max_trace_payload_chars",
            8000,
        ),
        slow_request_ms=_read_int(config, "observability.slow_request_ms", 5000),
        slow_llm_call_ms=_read_int(config, "observability.slow_llm_call_ms", 30000),
        slow_tool_call_ms=_read_int(config, "observability.slow_tool_call_ms", 10000),
        metrics_enabled=_read_bool(config, "observability.metrics_enabled", True),
    )


def get_health_settings(config: ConfigurationView) -> HealthSettings:
    """Resolve typed health settings from validated configuration."""

    return HealthSettings(
        expose_config_summary=_read_bool(config, "health.expose_config_summary", True),
        expose_provider_names=_read_bool(config, "health.expose_provider_names", True),
        expose_secret_values=_read_bool(config, "health.expose_secret_values", False),
        include_component_details=_read_bool(config, "health.include_component_details", True),
    )


def get_deployment_settings(config: ConfigurationView) -> DeploymentSettings:
    """Resolve typed deployment settings from validated configuration."""

    profile = _read_str(
        config,
        "deployment.profile",
        _read_str(config, "app.environment", "local"),
    )
    log_dir = _read_resolved_backend_path(config, "deployment.log_dir", default="logs")
    runtime_dir = _read_resolved_backend_path(config, "deployment.runtime_dir", default="runtime")

    return DeploymentSettings(
        profile=profile,
        host=_read_str(config, "deployment.host", "127.0.0.1"),
        port=_read_int(config, "deployment.port", 8000),
        public_base_url=_read_optional_str_or_none(config, "deployment.public_base_url"),
        log_dir=log_dir,
        runtime_dir=runtime_dir,
        graceful_shutdown_seconds=_read_int(
            config,
            "deployment.graceful_shutdown_seconds",
            20,
        ),
        metrics=DeploymentMetricsSettings(
            enabled=_read_bool(config, "deployment.metrics.enabled", True),
            bind_host=_read_str(config, "deployment.metrics.bind_host", "127.0.0.1"),
            port=_read_int(config, "deployment.metrics.port", 9102),
        ),
        readiness=DeploymentReadinessSettings(
            enabled=_read_bool(config, "deployment.readiness.enabled", True),
            bind_host=_read_optional_str_or_none(config, "deployment.readiness.bind_host"),
            port=_read_optional_int(config, "deployment.readiness.port"),
        ),
    )


def get_policy_settings(config: ConfigurationView) -> PolicySettings:
    """Resolve typed policy settings from validated configuration."""

    profile_sections = config.get("policy.profiles", {})
    if not isinstance(profile_sections, Mapping):
        raise ConfigurationError("Invalid config value at policy.profiles: expected mapping.")

    root_mode = _read_str(config, "policy.mode", "enforce")
    root_default_decision = _read_str(config, "policy.default_decision", "deny")
    root_fail_closed = _read_bool(config, "policy.fail_closed", True)

    profiles: dict[str, PolicyProfileSettings] = {}
    for profile_name, profile_section in profile_sections.items():
        if not isinstance(profile_name, str):
            raise ConfigurationError("Invalid config value at policy.profiles: expected string keys.")
        if not isinstance(profile_section, Mapping):
            raise ConfigurationError(
                f"Invalid config value at policy.profiles.{profile_name}: expected mapping."
            )

        profile_view = ValidatedConfigurationView({"profile": _unfreeze(profile_section)})

        deny_unknown_tools = _read_bool(
            profile_view,
            "profile.tools.deny_unknown_tools",
            _read_bool(profile_view, "profile.deny_unknown_tools", True),
        )
        deny_unknown_llm_profiles = _read_bool(
            profile_view,
            "profile.llm.deny_unknown_profiles",
            _read_bool(profile_view, "profile.deny_unknown_llm_profiles", True),
        )
        require_memory_scope = _read_bool(
            profile_view,
            "profile.memory.require_scope",
            _read_bool(profile_view, "profile.require_memory_scope", True),
        )
        allow_memory_writes = _read_bool(
            profile_view,
            "profile.memory.allow_writes",
            _read_bool(profile_view, "profile.allow_memory_writes", False),
        )
        allow_write_tools = _read_bool(
            profile_view,
            "profile.tools.allow_write_tools",
            _read_bool(profile_view, "profile.allow_write_tools", False),
        )
        allow_destructive_tools = _read_bool(
            profile_view,
            "profile.tools.allow_destructive_tools",
            _read_bool(profile_view, "profile.allow_destructive_tools", False),
        )
        allow_external_side_effect_tools = _read_bool(
            profile_view,
            "profile.tools.allow_external_side_effect_tools",
            _read_bool(
                profile_view,
                "profile.allow_external_side_effect_tools",
                False,
            ),
        )
        allow_approval_required_tools = _read_bool(
            profile_view,
            "profile.tools.allow_approval_required_tools",
            _read_bool(profile_view, "profile.allow_approval_required_tools", False),
        )
        profile_fail_closed = _read_optional_bool(profile_view, "profile.fail_closed")

        profiles[profile_name] = PolicyProfileSettings(
            name=profile_name,
            enabled=_read_bool(profile_view, "profile.enabled", True),
            mode=cast(
                Literal["enforce", "report_only"],
                _read_optional_str(profile_view, "profile.mode", fallback=root_mode),
            ),
            default_decision=cast(
                Literal["allow", "deny"],
                _read_optional_str(
                    profile_view,
                    "profile.default_decision",
                    fallback=root_default_decision,
                ),
            ),
            fail_closed=root_fail_closed if profile_fail_closed is None else profile_fail_closed,
            deny_unknown_tools=deny_unknown_tools,
            deny_unknown_llm_profiles=deny_unknown_llm_profiles,
            require_memory_scope=require_memory_scope,
            allow_memory_writes=allow_memory_writes,
            allow_write_tools=allow_write_tools,
            allow_destructive_tools=allow_destructive_tools,
            allow_external_side_effect_tools=allow_external_side_effect_tools,
            allow_approval_required_tools=allow_approval_required_tools,
            usecases=PolicyNamedAccessSettings(
                allowed=_read_str_tuple(profile_view, "profile.usecases.allowed", ()),
            ),
            strategies=PolicyNamedAccessSettings(
                allowed=_read_str_tuple(profile_view, "profile.strategies.allowed", ()),
            ),
            agents=PolicyNamedAccessSettings(
                allowed=_read_str_tuple(profile_view, "profile.agents.allowed", ()),
            ),
            llm=PolicyLLMSettings(
                deny_unknown_profiles=deny_unknown_llm_profiles,
                allowed_profiles=_read_str_tuple(
                    profile_view,
                    "profile.llm.allowed_profiles",
                    (),
                ),
                allow_prompt_trace=_read_bool(
                    profile_view,
                    "profile.llm.allow_prompt_trace",
                    False,
                ),
                allow_completion_trace=_read_bool(
                    profile_view,
                    "profile.llm.allow_completion_trace",
                    False,
                ),
            ),
            memory=PolicyMemorySettings(
                require_scope=require_memory_scope,
                allow_writes=allow_memory_writes,
                allowed_read_scopes=_read_str_tuple(
                    profile_view,
                    "profile.memory.allowed_read_scopes",
                    (),
                ),
                allowed_write_scopes=_read_str_tuple(
                    profile_view,
                    "profile.memory.allowed_write_scopes",
                    (),
                ),
            ),
            tools=PolicyToolSettings(
                deny_unknown_tools=deny_unknown_tools,
                allowed_tools=_read_str_tuple(
                    profile_view,
                    "profile.tools.allowed_tools",
                    (),
                ),
                allow_write_tools=allow_write_tools,
                allow_destructive_tools=allow_destructive_tools,
                allow_external_side_effect_tools=allow_external_side_effect_tools,
                allow_approval_required_tools=allow_approval_required_tools,
            ),
            approval=PolicyApprovalSettings(
                require_approval_for_write_tools=_read_bool(
                    profile_view,
                    "profile.approval.require_approval_for_write_tools",
                    True,
                ),
                require_approval_for_destructive_tools=_read_bool(
                    profile_view,
                    "profile.approval.require_approval_for_destructive_tools",
                    True,
                ),
                require_approval_for_external_side_effect_tools=_read_bool(
                    profile_view,
                    "profile.approval.require_approval_for_external_side_effect_tools",
                    True,
                ),
                require_approval_for_memory_writes=_read_bool(
                    profile_view,
                    "profile.approval.require_approval_for_memory_writes",
                    False,
                ),
            ),
            fallback=PolicyFallbackSettings(
                allow_fallbacks=_read_bool(
                    profile_view,
                    "profile.fallback.allow_fallbacks",
                    True,
                ),
                allow_after_denial=_read_bool(
                    profile_view,
                    "profile.fallback.allow_after_denial",
                    False,
                ),
                allow_after_external_side_effects=_read_bool(
                    profile_view,
                    "profile.fallback.allow_after_external_side_effects",
                    False,
                ),
                allowed_strategies=_read_str_tuple(
                    profile_view,
                    "profile.fallback.allowed_strategies",
                    (),
                ),
            ),
            trace=PolicyTraceSettings(
                allow_trace=_read_bool(profile_view, "profile.trace.allow_trace", True),
                expose_raw_payloads=_read_bool(
                    profile_view,
                    "profile.trace.expose_raw_payloads",
                    False,
                ),
                expose_prompt_text=_read_bool(
                    profile_view,
                    "profile.trace.expose_prompt_text",
                    False,
                ),
                expose_completion_text=_read_bool(
                    profile_view,
                    "profile.trace.expose_completion_text",
                    False,
                ),
            ),
            stream=PolicyStreamSettings(
                allow_stream_events=_read_bool(
                    profile_view,
                    "profile.stream.allow_stream_events",
                    True,
                ),
                expose_internal_events=_read_bool(
                    profile_view,
                    "profile.stream.expose_internal_events",
                    False,
                ),
                expose_raw_deltas=_read_bool(
                    profile_view,
                    "profile.stream.expose_raw_deltas",
                    False,
                ),
            ),
            capabilities=PolicyCapabilitySettings(
                expose_enabled=_read_bool(
                    profile_view,
                    "profile.capabilities.expose_enabled",
                    True,
                ),
                include_policy_profiles=_read_bool(
                    profile_view,
                    "profile.capabilities.include_policy_profiles",
                    False,
                ),
                include_denied_actions=_read_bool(
                    profile_view,
                    "profile.capabilities.include_denied_actions",
                    False,
                ),
            ),
            health=PolicyHealthSettings(
                expose_enabled=_read_bool(
                    profile_view,
                    "profile.health.expose_enabled",
                    True,
                ),
                include_profile_names=_read_bool(
                    profile_view,
                    "profile.health.include_profile_names",
                    True,
                ),
                include_decision_counts=_read_bool(
                    profile_view,
                    "profile.health.include_decision_counts",
                    False,
                ),
            ),
            audit=PolicyAuditSettings(
                enabled=_read_bool(profile_view, "profile.audit.enabled", True),
                include_reason_codes=_read_bool(
                    profile_view,
                    "profile.audit.include_reason_codes",
                    True,
                ),
                include_actor_identifiers=_read_bool(
                    profile_view,
                    "profile.audit.include_actor_identifiers",
                    False,
                ),
                include_resource_names=_read_bool(
                    profile_view,
                    "profile.audit.include_resource_names",
                    True,
                ),
            ),
            decision_cache=PolicyDecisionCacheSettings(
                enabled=_read_bool(
                    profile_view,
                    "profile.decision_cache.enabled",
                    True,
                ),
                ttl_seconds=_read_int(
                    profile_view,
                    "profile.decision_cache.ttl_seconds",
                    30,
                ),
                max_entries=_read_int(
                    profile_view,
                    "profile.decision_cache.max_entries",
                    1024,
                ),
            ),
        )

    return PolicySettings(
        enabled=_read_bool(config, "policy.enabled", True),
        mode=cast(Literal["enforce", "report_only"], root_mode),
        default_profile=_read_str(config, "policy.default_profile", "default"),
        default_decision=cast(Literal["allow", "deny"], root_default_decision),
        fail_closed=root_fail_closed,
        profiles=profiles,
    )


def get_api_settings(config: ConfigurationView) -> ApiSettings:
    """Resolve typed API settings from validated configuration."""

    session_settings = get_session_settings(config)

    return ApiSettings(
        enabled=_read_bool(config, "api.enabled", True),
        base_path=_read_str(config, "api.base_path", ""),
        docs_enabled=_read_bool(config, "api.docs_enabled", True),
        openapi_enabled=_read_bool(config, "api.openapi_enabled", True),
        cors=CorsSettings(
            enabled=_read_bool(config, "api.cors.enabled", False),
            allow_origins=_read_str_tuple(config, "api.cors.allow_origins", ()),
            allow_credentials=_read_bool(config, "api.cors.allow_credentials", True),
            allow_methods=_read_str_tuple(
                config,
                "api.cors.allow_methods",
                ("GET", "POST", "OPTIONS"),
            ),
            allow_headers=_read_str_tuple(
                config,
                "api.cors.allow_headers",
                ("Authorization", "Content-Type", "X-Request-Id", "X-Trace-Id"),
            ),
        ),
        request_limits=ApiRequestLimitSettings(
            max_body_bytes=_read_int(config, "api.request_limits.max_body_bytes", 1048576),
            max_message_chars=_read_int(
                config,
                "api.request_limits.max_message_chars",
                20000,
            ),
            max_metadata_bytes=_read_int(
                config,
                "api.request_limits.max_metadata_bytes",
                65536,
            ),
            request_timeout_seconds=_read_int(
                config,
                "api.request_limits.request_timeout_seconds",
                120,
            ),
            stream_timeout_seconds=_read_int(
                config,
                "api.request_limits.stream_timeout_seconds",
                300,
            ),
        ),
        sessions=ApiSessionSettings(
            accept_client_session_id=session_settings.identifiers.accept_client_session_id,
            create_session_when_missing=session_settings.identifiers.generate_when_missing,
            session_id_header=_read_str(
                config,
                "api.sessions.session_id_header",
                "X-Session-Id",
            ),
        ),
        tracing=ApiTracingSettings(
            accept_client_trace_id=_read_bool(
                config,
                "api.tracing.accept_client_trace_id",
                True,
            ),
            response_trace_header=_read_str(
                config,
                "api.tracing.response_trace_header",
                "X-Trace-Id",
            ),
            record_request_received=_read_bool(
                config,
                "api.tracing.record_request_received",
                True,
            ),
            record_response_returned=_read_bool(
                config,
                "api.tracing.record_response_returned",
                True,
            ),
            record_validation_errors=_read_bool(
                config,
                "api.tracing.record_validation_errors",
                True,
            ),
        ),
        debug_routes=ApiDebugRoutesSettings(
            enabled=_read_bool(config, "api.debug_routes.enabled", False),
            require_localhost=_read_bool(
                config,
                "api.debug_routes.require_localhost",
                True,
            ),
            restart_enabled=_read_bool(
                config,
                "api.debug_routes.restart_enabled",
                False,
            ),
            max_trace_events=_read_int(
                config,
                "api.debug_routes.max_trace_events",
                500,
            ),
            max_search_results=_read_int(
                config,
                "api.debug_routes.max_search_results",
                50,
            ),
        ),
        sse=ApiSseSettings(
            heartbeat_seconds=_read_int(config, "api.sse.heartbeat_seconds", 15),
            send_trace_id_event=_read_bool(
                config,
                "api.sse.send_trace_id_event",
                True,
            ),
            send_metadata_events=_read_bool(
                config,
                "api.sse.send_metadata_events",
                True,
            ),
        ),
    )


def get_orchestration_settings(config: ConfigurationView) -> OrchestrationSettings:
    """Resolve typed orchestration settings from validated configuration."""

    strategy_sections = _read_mapping_section(
        config,
        primary_path="orchestration.strategies",
        fallback_path="strategies",
    )
    usecase_sections = _read_mapping_section(
        config,
        primary_path="orchestration.usecases",
        fallback_path="usecases",
    )

    strategies: dict[str, StrategySettings] = {}
    for strategy_name, strategy_section in strategy_sections.items():
        if not isinstance(strategy_name, str):
            raise ConfigurationError(
                "Invalid config value at orchestration.strategies: expected string keys."
            )
        if not isinstance(strategy_section, Mapping):
            raise ConfigurationError(
                f"Invalid config value at orchestration.strategies.{strategy_name}: "
                "expected mapping."
            )

        strategy_view = ValidatedConfigurationView(
            {"strategy": _unfreeze(strategy_section)}
        )
        strategy_type = _normalize_strategy_type(
            _read_str(strategy_view, "strategy.type", "direct_agent"),
            path=f"orchestration.strategies.{strategy_name}.type",
        )
        strategies[strategy_name] = StrategySettings(
            name=strategy_name,
            enabled=_read_bool(strategy_view, "strategy.enabled", True),
            type=cast(StrategyType, strategy_type),
            description=_read_optional_str_or_none(strategy_view, "strategy.description"),
            default_agent=_read_optional_str_or_none(strategy_view, "strategy.default_agent"),
            allowed_usecases=_read_str_tuple(
                strategy_view,
                "strategy.allowed_usecases",
                (),
            ),
            llm_profile=_read_optional_str_or_none(strategy_view, "strategy.llm_profile"),
            planner_llm_profile=_read_optional_str_or_none(
                strategy_view,
                "strategy.planner_llm_profile",
            ),
            executor_llm_profile=_read_optional_str_or_none(
                strategy_view,
                "strategy.executor_llm_profile",
            ),
            memory_enabled=_read_bool(strategy_view, "strategy.memory_enabled", False),
            memory_write_enabled=_read_bool(
                strategy_view,
                "strategy.memory_write_enabled",
                False,
            ),
            tools_enabled=_read_bool(strategy_view, "strategy.tools_enabled", False),
            max_steps=_read_optional_int(strategy_view, "strategy.max_steps"),
            max_tool_calls=_read_optional_int(strategy_view, "strategy.max_tool_calls"),
            max_memory_searches=_read_optional_int(
                strategy_view,
                "strategy.max_memory_searches",
            ),
            max_memory_writes=_read_optional_int(
                strategy_view,
                "strategy.max_memory_writes",
            ),
            max_llm_calls=_read_optional_int(strategy_view, "strategy.max_llm_calls"),
            max_tool_loop_iterations=_read_optional_int(
                strategy_view,
                "strategy.max_tool_loop_iterations",
            ),
            max_context_bytes=_read_optional_int(
                strategy_view,
                "strategy.max_context_bytes",
            ),
            max_plan_steps=_read_optional_int(strategy_view, "strategy.max_plan_steps"),
            max_execute_steps=_read_optional_int(
                strategy_view,
                "strategy.max_execute_steps",
            ),
            max_candidate_agents=_read_optional_int(
                strategy_view,
                "strategy.max_candidate_agents",
            ),
            candidate_limit=_read_optional_int(strategy_view, "strategy.candidate_limit"),
            candidate_strategies=_read_str_tuple(
                strategy_view,
                "strategy.candidate_strategies",
                (),
            ),
            fallback_strategy=_read_optional_str_or_none(
                strategy_view,
                "strategy.fallback_strategy",
            ),
            require_policy_approval=_read_bool(
                strategy_view,
                "strategy.require_policy_approval",
                False,
            ),
            stream_llm_deltas=_read_bool(
                strategy_view,
                "strategy.stream_llm_deltas",
                True,
            ),
            stream_tool_events=_read_bool(
                strategy_view,
                "strategy.stream_tool_events",
                True,
            ),
            stream_strategy_events=_read_optional_bool(
                strategy_view,
                "strategy.stream_strategy_events",
            ),
            expose_strategy_metadata=_read_bool(
                strategy_view,
                "strategy.expose_strategy_metadata",
                True,
            ),
            message=_read_optional_str_or_none(strategy_view, "strategy.message"),
            memory=OrchestrationStrategyMemorySettings(
                default_limit=_read_int(strategy_view, "strategy.memory.default_limit", 10),
                include_document_chunks=_read_bool(
                    strategy_view,
                    "strategy.memory.include_document_chunks",
                    True,
                ),
                include_user_memory=_read_bool(
                    strategy_view,
                    "strategy.memory.include_user_memory",
                    True,
                ),
                min_score=_read_optional_float(strategy_view, "strategy.memory.min_score"),
                max_context_items=_read_optional_int(
                    strategy_view,
                    "strategy.memory.max_context_items",
                ),
                max_context_bytes=_read_optional_int(
                    strategy_view,
                    "strategy.memory.max_context_bytes",
                ),
            ),
            tools=OrchestrationStrategyToolSettings(
                max_calls=_read_optional_int(strategy_view, "strategy.tools.max_calls"),
                max_tool_loop_iterations=_read_optional_int(
                    strategy_view,
                    "strategy.tools.max_tool_loop_iterations",
                ),
                allowed_safety_levels=_read_str_tuple(
                    strategy_view,
                    "strategy.tools.allowed_safety_levels",
                    (),
                ),
                allowed_tools=_read_str_tuple(
                    strategy_view,
                    "strategy.tools.allowed_tools",
                    (),
                ),
                stream_tool_events=_read_bool(
                    strategy_view,
                    "strategy.tools.stream_tool_events",
                    True,
                ),
            ),
            metadata=_read_mapping_dict(strategy_view, "strategy.metadata"),
        )

    usecases: dict[str, UseCaseSettings] = {}
    for usecase_name, usecase_section in usecase_sections.items():
        if not isinstance(usecase_name, str):
            raise ConfigurationError(
                "Invalid config value at orchestration.usecases: expected string keys."
            )
        if not isinstance(usecase_section, Mapping):
            raise ConfigurationError(
                f"Invalid config value at orchestration.usecases.{usecase_name}: "
                "expected mapping."
            )

        usecase_view = ValidatedConfigurationView({"usecase": _unfreeze(usecase_section)})
        agent_name = _read_optional_str_or_none(usecase_view, "usecase.agent") or _read_optional_str_or_none(
            usecase_view,
            "usecase.default_agent",
        )
        allowed_agents = _read_str_tuple(usecase_view, "usecase.allowed_agents", ())
        if not allowed_agents and agent_name is not None:
            allowed_agents = (agent_name,)

        usecases[usecase_name] = UseCaseSettings(
            name=usecase_name,
            enabled=_read_bool(usecase_view, "usecase.enabled", True),
            strategy=_read_str(usecase_view, "usecase.strategy", ""),
            agent=agent_name,
            llm_profile=_read_optional_str_or_none(usecase_view, "usecase.llm_profile")
            or _read_optional_str_or_none(
                usecase_view,
                "usecase.orchestrator_llm_profile",
            ),
            display_name=_read_optional_str_or_none(usecase_view, "usecase.display_name"),
            description=_read_optional_str_or_none(usecase_view, "usecase.description"),
            allowed_agents=allowed_agents,
            allowed_strategies=_read_str_tuple(
                usecase_view,
                "usecase.allowed_strategies",
                (),
            ),
            policy_profile=_read_str(usecase_view, "usecase.policy_profile", "default"),
            memory=OrchestrationUseCaseMemorySettings(
                enabled=_read_bool(usecase_view, "usecase.memory.enabled", True),
                include_document_chunks=_read_bool(
                    usecase_view,
                    "usecase.memory.include_document_chunks",
                    True,
                ),
                default_limit=_read_int(usecase_view, "usecase.memory.default_limit", 10),
                allowed_project_ids=_read_str_tuple(
                    usecase_view,
                    "usecase.memory.allowed_project_ids",
                    (),
                ),
                default_project_id=_read_optional_str_or_none(
                    usecase_view,
                    "usecase.memory.default_project_id",
                ),
            ),
            tools=OrchestrationUseCaseToolSettings(
                enabled=_read_bool(usecase_view, "usecase.tools.enabled", True),
                allowed_tools=_read_str_tuple(
                    usecase_view,
                    "usecase.tools.allowed_tools",
                    (),
                ),
            ),
            metadata=_read_mapping_dict(usecase_view, "usecase.metadata"),
        )

    default_strategy = _read_optional_str_or_none(config, "orchestration.defaults.strategy")
    if default_strategy is None:
        active_usecase = _read_optional_str_or_none(config, "session.defaults.default_usecase") or _read_optional_str_or_none(
            config,
            "app.active_usecase",
        )
        if active_usecase is not None:
            resolved_usecase = usecases.get(active_usecase)
            if resolved_usecase is not None:
                default_strategy = resolved_usecase.strategy

    if default_strategy is None:
        raise ConfigurationError("Missing required config path: orchestration.defaults.strategy")

    fallback_strategy = _read_optional_str_or_none(
        config,
        "orchestration.defaults.fallback_strategy",
    ) or default_strategy

    return OrchestrationSettings(
        enabled=_read_bool(config, "orchestration.enabled", True),
        defaults=OrchestrationDefaultsSettings(
            strategy=default_strategy,
            fallback_strategy=fallback_strategy,
            max_steps=_read_int(config, "orchestration.defaults.max_steps", 8),
            max_tool_calls=_read_int(
                config,
                "orchestration.defaults.max_tool_calls",
                4,
            ),
            max_memory_searches=_read_int(
                config,
                "orchestration.defaults.max_memory_searches",
                3,
            ),
            max_memory_writes=_read_int(
                config,
                "orchestration.defaults.max_memory_writes",
                1,
            ),
            max_llm_calls=_read_int(config, "orchestration.defaults.max_llm_calls", 6),
            max_tool_loop_iterations=_read_int(
                config,
                "orchestration.defaults.max_tool_loop_iterations",
                3,
            ),
            max_context_bytes=_read_int(
                config,
                "orchestration.defaults.max_context_bytes",
                64000,
            ),
            max_turn_duration_seconds=_read_int(
                config,
                "orchestration.defaults.max_turn_duration_seconds",
                120,
            ),
            max_stream_duration_seconds=_read_int(
                config,
                "orchestration.defaults.max_stream_duration_seconds",
                300,
            ),
            emit_step_events=_read_bool(
                config,
                "orchestration.defaults.emit_step_events",
                True,
            ),
            emit_tool_events=_read_bool(
                config,
                "orchestration.defaults.emit_tool_events",
                True,
            ),
            emit_memory_events=_read_bool(
                config,
                "orchestration.defaults.emit_memory_events",
                True,
            ),
            stream_strategy_events=_read_bool(
                config,
                "orchestration.defaults.stream_strategy_events",
                True,
            ),
            expose_strategy_metadata=_read_bool(
                config,
                "orchestration.defaults.expose_strategy_metadata",
                True,
            ),
            expose_chain_of_thought=_read_bool(
                config,
                "orchestration.defaults.expose_chain_of_thought",
                False,
            ),
            save_runtime_snapshots=_read_bool(
                config,
                "orchestration.defaults.save_runtime_snapshots",
                False,
            ),
            conversation_context=ConversationContextSettings(
                enabled=_read_bool(
                    config,
                    "orchestration.defaults.conversation_context.enabled",
                    False,
                ),
                mode=_read_str(
                    config,
                    "orchestration.defaults.conversation_context.mode",
                    "window",
                ),
                max_messages=_read_int(
                    config,
                    "orchestration.defaults.conversation_context.max_messages",
                    12,
                ),
                max_chars=_read_int(
                    config,
                    "orchestration.defaults.conversation_context.max_chars",
                    12000,
                ),
                include_assistant_messages=_read_bool(
                    config,
                    "orchestration.defaults.conversation_context.include_assistant_messages",
                    True,
                ),
                summary_threshold_messages=_read_int(
                    config,
                    "orchestration.defaults.conversation_context.summary_threshold_messages",
                    24,
                ),
                summary_max_chars=_read_int(
                    config,
                    "orchestration.defaults.conversation_context.summary_max_chars",
                    2000,
                ),
            ),
        ),
        strategies=strategies,
        usecases=usecases,
    )


def get_llm_settings(config: ConfigurationView) -> LLMSettings:
    """Resolve typed LLM settings from validated configuration."""

    provider_sections = config.section("llm.providers")
    profile_sections = config.section("llm.profiles")

    default_profile = config.get("llm.defaults.profile", config.get("llm.default_profile", None))
    if not isinstance(default_profile, str):
        raise ConfigurationError("Missing required config path: llm.defaults.profile")

    providers: dict[str, LLMProviderSettings] = {}
    for provider_name in provider_sections:
        prefix = f"llm.providers.{provider_name}"
        providers[provider_name] = LLMProviderSettings(
            name=provider_name,
            type=_read_str(config, f"{prefix}.type", "openai_compatible"),
            enabled=_read_bool(config, f"{prefix}.enabled", True),
            base_url=_read_optional_str_or_none(config, f"{prefix}.base_url"),
            endpoint=_read_optional_str_or_none(config, f"{prefix}.endpoint"),
            api_key=_read_optional_str_or_none(config, f"{prefix}.api_key"),
            auth_header=_read_optional_str_or_none(config, f"{prefix}.auth_header"),
            auth_token=_read_optional_str_or_none(config, f"{prefix}.auth_token"),
            timeout_seconds=_read_int(config, f"{prefix}.timeout_seconds", 120),
            stream_timeout_seconds=_read_int(
                config,
                f"{prefix}.stream_timeout_seconds",
                300,
            ),
            headers=_read_str_mapping(config, f"{prefix}.headers"),
            extra=_read_mapping_dict(config, f"{prefix}.extra"),
        )

    profiles: dict[str, LLMProfileSettings] = {}
    for profile_name in profile_sections:
        prefix = f"llm.profiles.{profile_name}"
        allow_prefix = f"{prefix}.allowed_for"
        profiles[profile_name] = LLMProfileSettings(
            name=profile_name,
            enabled=_read_bool(config, f"{prefix}.enabled", True),
            provider=_read_str(config, f"{prefix}.provider", ""),
            model=_read_str(config, f"{prefix}.model", ""),
            temperature=_read_optional_float(config, f"{prefix}.temperature"),
            top_p=_read_optional_float(config, f"{prefix}.top_p"),
            max_output_tokens=_read_optional_int(config, f"{prefix}.max_output_tokens"),
            max_input_tokens=_read_optional_int(config, f"{prefix}.max_input_tokens"),
            max_total_tokens=_read_optional_int(config, f"{prefix}.max_total_tokens"),
            timeout_seconds=_read_optional_int(config, f"{prefix}.timeout_seconds"),
            stream_timeout_seconds=_read_optional_int(
                config,
                f"{prefix}.stream_timeout_seconds",
            ),
            supports_streaming=_read_bool(config, f"{prefix}.supports_streaming", True),
            supports_json_schema=_read_bool(
                config,
                f"{prefix}.supports_json_schema",
                False,
            ),
            supports_tool_calling=_read_bool(
                config,
                f"{prefix}.supports_tool_calling",
                False,
            ),
            allowed_for=LLMProfileAllowlistSettings(
                usecases=_read_str_tuple(config, f"{allow_prefix}.usecases", ()),
                agents=_read_str_tuple(config, f"{allow_prefix}.agents", ()),
                strategies=_read_str_tuple(config, f"{allow_prefix}.strategies", ()),
            ),
            fallback_profiles=_read_str_tuple(config, f"{prefix}.fallback_profiles", ()),
            extra=_read_mapping_dict(config, f"{prefix}.extra"),
        )

    return LLMSettings(
        defaults=LLMDefaultsSettings(
            profile=default_profile,
            timeout_seconds=_read_int(config, "llm.defaults.timeout_seconds", 120),
            stream_timeout_seconds=_read_int(
                config,
                "llm.defaults.stream_timeout_seconds",
                300,
            ),
            max_retries=_read_int(config, "llm.defaults.max_retries", 1),
            trace_prompts=_read_bool(config, "llm.defaults.trace_prompts", False),
            trace_completions=_read_bool(
                config,
                "llm.defaults.trace_completions",
                False,
            ),
        ),
        providers=providers,
        profiles=profiles,
    )


def get_agents_settings(config: ConfigurationView) -> AgentsSettings:
    """Resolve typed agent settings from validated configuration."""

    plugin_sections = _read_agent_plugin_sections(config)

    default_limits = AgentLimitSettings(
        max_prompt_context_bytes=_read_int(
            config,
            "agents.defaults.max_prompt_context_bytes",
            32000,
        ),
        max_output_chars=_read_int(config, "agents.defaults.max_output_chars", 12000),
        max_tool_intents=_read_int(config, "agents.defaults.max_tool_intents", 3),
        max_memory_candidates=_read_int(
            config,
            "agents.defaults.max_memory_candidates",
            5,
        ),
        max_llm_calls=_read_int(config, "agents.defaults.max_llm_calls", 1),
        max_self_managed_tool_calls=_read_int(
            config,
            "agents.defaults.max_self_managed_tool_calls",
            0,
        ),
        max_self_managed_memory_searches=_read_int(
            config,
            "agents.defaults.max_self_managed_memory_searches",
            0,
        ),
    )
    default_context_policy = AgentContextPolicySettings(
        require_context_for_grounded_claims=False,
        cite_context_labels=True,
        max_context_items=8,
        max_context_bytes=default_limits.max_prompt_context_bytes,
        allow_untrusted_context_instructions=False,
    )

    plugins: dict[str, AgentPluginSettings] = {}
    for plugin_name, plugin_section in plugin_sections.items():
        if not isinstance(plugin_name, str):
            raise ConfigurationError(
                "Invalid config value at agents.plugins: expected string keys."
            )
        if not isinstance(plugin_section, Mapping):
            raise ConfigurationError(
                f"Invalid config value at agents.plugins.{plugin_name}: expected mapping."
            )

        plugin_view = ValidatedConfigurationView({"agent": _unfreeze(plugin_section)})
        plugins[plugin_name] = AgentPluginSettings(
            name=plugin_name,
            type=cast(AgentType, _read_str(plugin_view, "agent.type", "custom")),
            enabled=_read_bool(
                plugin_view,
                "agent.enabled",
                _read_bool(config, "agents.defaults.enabled", True),
            ),
            display_name=_read_optional_str_or_none(plugin_view, "agent.display_name"),
            description=_read_optional_str_or_none(plugin_view, "agent.description"),
            llm_profile=_read_optional_str_or_none(plugin_view, "agent.llm_profile"),
            prompt_profile=_read_optional_str_or_none(plugin_view, "agent.prompt_profile"),
            capabilities=AgentCapabilitySettings(
                answer=_read_bool(plugin_view, "agent.capabilities.answer", True),
                review=_read_bool(plugin_view, "agent.capabilities.review", False),
                stream=_read_bool(plugin_view, "agent.capabilities.stream", True),
                memory_read=_read_bool(
                    plugin_view,
                    "agent.capabilities.memory_read",
                    False,
                ),
                memory_write=_read_bool(
                    plugin_view,
                    "agent.capabilities.memory_write",
                    False,
                ),
                memory_candidate_extract=_read_bool(
                    plugin_view,
                    "agent.capabilities.memory_candidate_extract",
                    False,
                ),
                tool_intents=_read_bool(
                    plugin_view,
                    "agent.capabilities.tool_intents",
                    False,
                ),
                tool_execute=_read_bool(
                    plugin_view,
                    "agent.capabilities.tool_execute",
                    False,
                ),
                self_managed_memory=_read_bool(
                    plugin_view,
                    "agent.capabilities.self_managed_memory",
                    False,
                ),
                self_managed_tools=_read_bool(
                    plugin_view,
                    "agent.capabilities.self_managed_tools",
                    False,
                ),
            ),
            limits=AgentLimitSettings(
                max_prompt_context_bytes=_read_int(
                    plugin_view,
                    "agent.limits.max_prompt_context_bytes",
                    default_limits.max_prompt_context_bytes,
                ),
                max_output_chars=_read_int(
                    plugin_view,
                    "agent.limits.max_output_chars",
                    default_limits.max_output_chars,
                ),
                max_tool_intents=_read_int(
                    plugin_view,
                    "agent.limits.max_tool_intents",
                    default_limits.max_tool_intents,
                ),
                max_memory_candidates=_read_int(
                    plugin_view,
                    "agent.limits.max_memory_candidates",
                    default_limits.max_memory_candidates,
                ),
                max_llm_calls=_read_int(
                    plugin_view,
                    "agent.limits.max_llm_calls",
                    default_limits.max_llm_calls,
                ),
                max_self_managed_tool_calls=_read_int(
                    plugin_view,
                    "agent.limits.max_self_managed_tool_calls",
                    default_limits.max_self_managed_tool_calls,
                ),
                max_self_managed_memory_searches=_read_int(
                    plugin_view,
                    "agent.limits.max_self_managed_memory_searches",
                    default_limits.max_self_managed_memory_searches,
                ),
            ),
            context_policy=AgentContextPolicySettings(
                require_context_for_grounded_claims=_read_bool(
                    plugin_view,
                    "agent.context_policy.require_context_for_grounded_claims",
                    default_context_policy.require_context_for_grounded_claims,
                ),
                cite_context_labels=_read_bool(
                    plugin_view,
                    "agent.context_policy.cite_context_labels",
                    default_context_policy.cite_context_labels,
                ),
                max_context_items=_read_int(
                    plugin_view,
                    "agent.context_policy.max_context_items",
                    default_context_policy.max_context_items,
                ),
                max_context_bytes=_read_int(
                    plugin_view,
                    "agent.context_policy.max_context_bytes",
                    default_context_policy.max_context_bytes,
                ),
                allow_untrusted_context_instructions=_read_bool(
                    plugin_view,
                    "agent.context_policy.allow_untrusted_context_instructions",
                    default_context_policy.allow_untrusted_context_instructions,
                ),
            ),
            allowed_tool_intents=_read_str_tuple(
                plugin_view,
                "agent.allowed_tool_intents",
                (),
            ),
            allowed_memory_scopes=_read_str_tuple(
                plugin_view,
                "agent.allowed_memory_scopes",
                (),
            ),
            memory=AgentMemorySettings(
                search_enabled=_read_bool(
                    plugin_view,
                    "agent.memory.search_enabled",
                    False,
                ),
                write_enabled=_read_bool(
                    plugin_view,
                    "agent.memory.write_enabled",
                    False,
                ),
                allowed_project_ids=_read_str_tuple(
                    plugin_view,
                    "agent.memory.allowed_project_ids",
                    (),
                ),
                default_project_id=_read_optional_str_or_none(
                    plugin_view,
                    "agent.memory.default_project_id",
                ),
            ),
            expose_metadata=_read_bool(
                plugin_view,
                "agent.expose_metadata",
                _read_bool(config, "agents.defaults.expose_agent_metadata", True),
            ),
            stream_llm_deltas=_read_bool(
                plugin_view,
                "agent.stream_llm_deltas",
                _read_bool(config, "agents.defaults.stream_llm_deltas", True),
            ),
            module=_read_optional_str_or_none(plugin_view, "agent.module"),
            class_name=_read_optional_str_or_none(plugin_view, "agent.class_name"),
            prompts=AgentPromptOverrideSettings(
                system_prompt=_read_optional_str_or_none(
                    plugin_view,
                    "agent.prompts.system_prompt",
                ),
                developer_prompt=_read_optional_str_or_none(
                    plugin_view,
                    "agent.prompts.developer_prompt",
                ),
            ),
            metadata=_read_mapping_dict(plugin_view, "agent.metadata"),
        )

    return AgentsSettings(
        enabled=_read_bool(config, "agents.defaults.enabled", True),
        stream_llm_deltas=_read_bool(config, "agents.defaults.stream_llm_deltas", True),
        expose_agent_metadata=_read_bool(
            config,
            "agents.defaults.expose_agent_metadata",
            True,
        ),
        strict_prompt_profile_validation=_read_bool(
            config,
            "agents.defaults.strict_prompt_profile_validation",
            False,
        ),
        known_prompt_profiles=_read_str_tuple(
            config,
            "agents.defaults.known_prompt_profiles",
            (),
        ),
        allow_self_managed_tools=_read_bool(
            config,
            "agents.defaults.allow_self_managed_tools",
            False,
        ),
        allow_self_managed_memory=_read_bool(
            config,
            "agents.defaults.allow_self_managed_memory",
            False,
        ),
        allow_memory_write=_read_bool(
            config,
            "agents.defaults.allow_memory_write",
            False,
        ),
        limits=default_limits,
        context_policy=default_context_policy,
        plugins=plugins,
    )


def get_tooling_settings(config: ConfigurationView) -> ToolingSettings:
    """Resolve typed tooling settings from validated configuration."""

    tool_sections = config.get("tooling.registry.tools", {})
    if not isinstance(tool_sections, Mapping):
        raise ConfigurationError(
            "Invalid config value at tooling.registry.tools: expected mapping."
        )

    tools: dict[str, ToolDefinitionSettings] = {}
    for tool_name, tool_section in tool_sections.items():
        if not isinstance(tool_name, str):
            raise ConfigurationError(
                "Invalid config value at tooling.registry.tools: expected string keys."
            )
        if not isinstance(tool_section, Mapping):
            raise ConfigurationError(
                f"Invalid config value at tooling.registry.tools.{tool_name}: "
                "expected mapping."
            )

        tool_view = ValidatedConfigurationView({"definition": _unfreeze(tool_section)})
        tools[str(tool_name)] = ToolDefinitionSettings(
            name=str(tool_name),
            enabled=_read_bool(tool_view, "definition.enabled", True),
            mcp_tool_name=_read_str(tool_view, "definition.mcp_tool_name", ""),
            description=_read_optional_str_or_none(tool_view, "definition.description"),
            allowed_for=ToolAllowedForSettings(
                usecases=_read_str_tuple(tool_view, "definition.allowed_for.usecases", ()),
                agents=_read_str_tuple(tool_view, "definition.allowed_for.agents", ()),
                strategies=_read_str_tuple(tool_view, "definition.allowed_for.strategies", ()),
            ),
            timeout_seconds=_read_optional_int(tool_view, "definition.timeout_seconds"),
            max_argument_bytes=_read_optional_int(
                tool_view,
                "definition.max_argument_bytes",
            ),
            max_result_bytes=_read_optional_int(tool_view, "definition.max_result_bytes"),
            approval_required=_read_bool(
                tool_view,
                "definition.approval_required",
                False,
            ),
            input_schema_override=_read_optional_mapping_dict(
                tool_view,
                "definition.input_schema_override",
            ),
            output_schema_override=_read_optional_mapping_dict(
                tool_view,
                "definition.output_schema_override",
            ),
            tags=_read_str_tuple(tool_view, "definition.tags", ()),
            safety_level=cast(
                Literal[
                    "read_only",
                    "write",
                    "destructive",
                    "external_side_effect",
                ],
                _read_str(tool_view, "definition.safety_level", "read_only"),
            ),
            extra=_read_mapping_dict(tool_view, "definition.extra"),
        )

    oauth_scopes: tuple[str, ...]
    if config.get("mcp.main.auth.oauth.scopes", None) is not None:
        oauth_scopes = _read_str_tuple(config, "mcp.main.auth.oauth.scopes", ())
    else:
        oauth_scopes = _read_str_tuple(config, "mcp.main.auth.scopes", ())

    return ToolingSettings(
        enabled=_read_bool(config, "tooling.enabled", False),
        defaults=ToolingDefaultsSettings(
            timeout_seconds=_read_int(config, "tooling.defaults.timeout_seconds", 60),
            stream_timeout_seconds=_read_int(
                config,
                "tooling.defaults.stream_timeout_seconds",
                300,
            ),
            max_retries=_read_int(config, "tooling.defaults.max_retries", 1),
            max_argument_bytes=_read_int(
                config,
                "tooling.defaults.max_argument_bytes",
                65536,
            ),
            max_result_bytes=_read_int(
                config,
                "tooling.defaults.max_result_bytes",
                262144,
            ),
            trace_arguments=_read_bool(
                config,
                "tooling.defaults.trace_arguments",
                False,
            ),
            trace_results=_read_bool(
                config,
                "tooling.defaults.trace_results",
                False,
            ),
            discovery_on_startup=_read_bool(
                config,
                "tooling.defaults.discovery_on_startup",
                True,
            ),
            discovery_refresh_seconds=_read_int(
                config,
                "tooling.defaults.discovery_refresh_seconds",
                300,
            ),
        ),
        mcp_server=MCPServerSettings(
            name=_read_str(config, "mcp.main.name", "main"),
            enabled=_read_bool(config, "mcp.main.enabled", True),
            endpoint=_read_optional_str_or_none(config, "mcp.main.url")
            or _read_optional_str_or_none(config, "mcp.main.endpoint"),
            transport=cast(
                Literal["http", "sse", "websocket"],
                _read_str(config, "mcp.main.transport", "http"),
            ),
            timeout_seconds=_read_int(config, "mcp.main.timeout_seconds", 60),
            stream_timeout_seconds=_read_int(
                config,
                "mcp.main.stream_timeout_seconds",
                300,
            ),
            auth=MCPAuthSettings(
                mode=cast(
                    Literal[
                        "none",
                        "bearer",
                        "jwt",
                        "oauth_client_credentials",
                    ],
                    _read_str(config, "mcp.main.auth.mode", "none"),
                ),
                token=_read_optional_str_or_none(config, "mcp.main.auth.token"),
                jwt=_read_optional_str_or_none(config, "mcp.main.auth.jwt"),
                token_url=_read_optional_str_or_none(
                    config,
                    "mcp.main.auth.oauth.token_url",
                )
                or _read_optional_str_or_none(config, "mcp.main.auth.token_url"),
                client_id=_read_optional_str_or_none(
                    config,
                    "mcp.main.auth.oauth.client_id",
                )
                or _read_optional_str_or_none(config, "mcp.main.auth.client_id"),
                client_secret=_read_optional_str_or_none(
                    config,
                    "mcp.main.auth.oauth.client_secret",
                )
                or _read_optional_str_or_none(
                    config,
                    "mcp.main.auth.client_secret",
                ),
                scopes=oauth_scopes,
            ),
            tool_discovery_enabled=_read_bool(
                config,
                "mcp.main.tool_discovery_enabled",
                True,
            ),
        ),
        registry=ToolRegistrySettings(
            allow_discovered_tools=_read_bool(
                config,
                "tooling.registry.allow_discovered_tools",
                True,
            ),
            require_configured_allowlist=_read_bool(
                config,
                "tooling.registry.require_configured_allowlist",
                True,
            ),
            tools=tools,
        ),
    )


def get_memory_settings(config: ConfigurationView) -> MemorySettings:
    """Resolve typed memory settings from validated configuration."""

    base_dir = _read_memory_base_dir(config)
    enabled = _read_optional_bool(config, "memory.enabled")
    required = _read_optional_bool(config, "memory.required")
    config_path = _read_optional_resolved_path(
        config,
        "memory.store.config_path",
        resolve_with=resolve_backend_path,
    ) or _read_optional_resolved_path(
        config,
        "persistence.memory.memory_store.config_path",
        resolve_with=resolve_backend_path,
    )

    top_level_database_path = _read_optional_resolved_path(
        config,
        "memory.store.database.path",
        resolve_with=lambda value: resolve_data_path(value, base_dir=base_dir),
    )
    legacy_adapter_database_path = _read_optional_resolved_path(
        config,
        "persistence.memory.memory_store.database_path",
        resolve_with=lambda value: resolve_data_path(value, base_dir=base_dir),
    )
    legacy_config_database_path = _read_optional_resolved_path(
        config,
        "persistence.memory.config.database_path",
        resolve_with=resolve_backend_path,
    )
    database_path = (
        top_level_database_path
        or legacy_adapter_database_path
        or legacy_config_database_path
        or resolve_data_path("memory", base_dir=base_dir)
    )

    default_scope = _read_optional_str_or_none(config, "memory.defaults.default_scope") or _read_optional_str_or_none(
        config,
        "persistence.memory.memory_store.default_scope",
    ) or "project"
    top_k = _read_optional_int(config, "memory.defaults.top_k")
    if top_k is None:
        top_k = _read_optional_int(config, "persistence.memory.memory_store.search_limit_default")
    limit_max = _read_optional_int(config, "memory.search.limit_max")
    if limit_max is None:
        limit_max = _read_optional_int(config, "persistence.memory.memory_store.search_limit_max")
    allow_writes = _read_optional_bool(config, "memory.lifecycle.allow_writes")
    if allow_writes is None:
        allow_writes = _read_optional_bool(config, "persistence.memory.memory_store.allow_writes")

    return MemorySettings(
        enabled=enabled if enabled is not None else _read_bool(config, "features.memory_enabled", False),
        provider=_read_optional_str_or_none(config, "memory.provider")
        or _read_optional_str_or_none(config, "persistence.memory.provider")
        or "memory_store",
        required=required if required is not None else _read_bool(config, "persistence.memory.required", False),
        defaults=MemoryDefaultsSettings(
            default_scope=default_scope,
            top_k=top_k if top_k is not None else 10,
            include_agent_memories=_read_bool(
                config,
                "memory.defaults.include_agent_memories",
                True,
            ),
            include_document_chunks=_read_bool(
                config,
                "memory.defaults.include_document_chunks",
                True,
            ),
            include_graph_context=_read_bool(
                config,
                "memory.defaults.include_graph_context",
                True,
            ),
            max_result_chars=_read_int(
                config,
                "memory.defaults.max_result_chars",
                1200,
            ),
            max_total_context_chars=_read_int(
                config,
                "memory.defaults.max_total_context_chars",
                8000,
            ),
            trace_query_capture=_read_str(
                config,
                "memory.defaults.trace_query_capture",
                "none",
            ),
            trace_result_content_capture=_read_str(
                config,
                "memory.defaults.trace_result_content_capture",
                "none",
            ),
        ),
        store=MemoryStoreSettings(
            config_path=config_path,
            database=MemoryStoreDatabaseSettings(
                path=database_path,
                create_if_missing=_read_bool(
                    config,
                    "memory.store.database.create_if_missing",
                    True,
                ),
                schema_version=_read_int(
                    config,
                    "memory.store.database.schema_version",
                    1,
                ),
                embedded_single_process=_read_bool(
                    config,
                    "memory.store.database.embedded_single_process",
                    True,
                ),
            ),
            embeddings=MemoryEmbeddingsSettings(
                provider=_read_str(
                    config,
                    "memory.store.embeddings.provider",
                    "fastembed",
                ),
                model=_read_str(
                    config,
                    "memory.store.embeddings.model",
                    "BAAI/bge-small-en-v1.5",
                ),
                model_version=_read_optional_str_or_none(
                    config,
                    "memory.store.embeddings.model_version",
                ),
                dimension=_read_optional_int(
                    config,
                    "memory.store.embeddings.dimension",
                ),
                batch_size=_read_int(
                    config,
                    "memory.store.embeddings.batch_size",
                    64,
                ),
                normalize=_read_bool(
                    config,
                    "memory.store.embeddings.normalize",
                    True,
                ),
                dimension_mismatch=_read_str(
                    config,
                    "memory.store.embeddings.dimension_mismatch",
                    "error",
                ),
            ),
            reranker=MemoryRerankerSettings(
                enabled=_read_bool(config, "memory.store.reranker.enabled", True),
                provider=_read_str(
                    config,
                    "memory.store.reranker.provider",
                    "fastembed",
                ),
                model=_read_str(
                    config,
                    "memory.store.reranker.model",
                    "Xenova/ms-marco-MiniLM-L-6-v2",
                ),
                model_version=_read_optional_str_or_none(
                    config,
                    "memory.store.reranker.model_version",
                ),
                top_n=_read_int(config, "memory.store.reranker.top_n", 60),
            ),
        ),
        chunking=MemoryChunkingSettings(
            strategy=_read_str(config, "memory.chunking.strategy", "markdown_section"),
            max_tokens=_read_int(config, "memory.chunking.max_tokens", 350),
            overlap_tokens=_read_int(config, "memory.chunking.overlap_tokens", 50),
            include_heading_path=_read_bool(
                config,
                "memory.chunking.include_heading_path",
                True,
            ),
            include_frontmatter_in_embedding=_read_bool(
                config,
                "memory.chunking.include_frontmatter_in_embedding",
                True,
            ),
            preserve_code_blocks=_read_bool(
                config,
                "memory.chunking.preserve_code_blocks",
                True,
            ),
            removed_chunk_policy=_read_str(
                config,
                "memory.chunking.removed_chunk_policy",
                "mark_removed",
            ),
        ),
        search=MemorySearchSettings(
            limit_max=limit_max if limit_max is not None else 30,
            vector_top_n=_read_int(config, "memory.search.vector_top_n", 30),
            fts_top_n=_read_int(config, "memory.search.fts_top_n", 30),
            rrf_k=_read_int(config, "memory.search.rrf_k", 60),
            graph_expansion_enabled=_read_bool(
                config,
                "memory.search.graph_expansion_enabled",
                True,
            ),
            graph_expansion_hops=_read_int(
                config,
                "memory.search.graph_expansion_hops",
                1,
            ),
            final_top_k=_read_int(config, "memory.search.final_top_k", 10),
            include_component_scores=_read_bool(
                config,
                "memory.search.include_component_scores",
                True,
            ),
            include_debug=_read_bool(config, "memory.search.include_debug", False),
        ),
        scoring=MemoryScoringSettings(
            weights=MemoryScoringWeightsSettings(
                reranker=_read_float(
                    config,
                    "memory.scoring.weights.reranker",
                    0.45,
                ),
                retrieval_fusion=_read_float(
                    config,
                    "memory.scoring.weights.retrieval_fusion",
                    0.15,
                ),
                vector=_read_float(config, "memory.scoring.weights.vector", 0.10),
                full_text=_read_float(
                    config,
                    "memory.scoring.weights.full_text",
                    0.08,
                ),
                temporal=_read_float(
                    config,
                    "memory.scoring.weights.temporal",
                    0.07,
                ),
                importance=_read_float(
                    config,
                    "memory.scoring.weights.importance",
                    0.06,
                ),
                confidence=_read_float(
                    config,
                    "memory.scoring.weights.confidence",
                    0.04,
                ),
                graph=_read_float(config, "memory.scoring.weights.graph", 0.03),
                user_rating=_read_float(
                    config,
                    "memory.scoring.weights.user_rating",
                    0.02,
                ),
            ),
        ),
        lifecycle=MemoryLifecycleSettings(
            allow_writes=allow_writes if allow_writes is not None else False,
            default_ttl_days=_read_optional_int(config, "memory.lifecycle.default_ttl_days"),
            contradiction_policy=_read_str(
                config,
                "memory.lifecycle.contradiction_policy",
                "keep_both_mark_conflict",
            ),
            supersede_policy=_read_str(
                config,
                "memory.lifecycle.supersede_policy",
                "mark_previous_superseded",
            ),
            require_durable_scope_for_writes=_read_bool(
                config,
                "memory.lifecycle.require_durable_scope_for_writes",
                True,
            ),
            allow_session_scope_only_writes=_read_bool(
                config,
                "memory.lifecycle.allow_session_scope_only_writes",
                False,
            ),
            require_durable_scope_for_delete_export=_read_bool(
                config,
                "memory.lifecycle.require_durable_scope_for_delete_export",
                True,
            ),
        ),
        privacy=MemoryPrivacySettings(
            default_sensitivity=_read_str(
                config,
                "memory.privacy.default_sensitivity",
                "internal",
            ),
            allow_llm_context_default=_read_bool(
                config,
                "memory.privacy.allow_llm_context_default",
                True,
            ),
            allow_retrieval_default=_read_bool(
                config,
                "memory.privacy.allow_retrieval_default",
                True,
            ),
            delete_by_scope_requires_confirm=_read_bool(
                config,
                "memory.privacy.delete_by_scope_requires_confirm",
                True,
            ),
            enable_export_by_scope=_read_bool(
                config,
                "memory.privacy.enable_export_by_scope",
                False,
            ),
            enable_delete_by_scope=_read_bool(
                config,
                "memory.privacy.enable_delete_by_scope",
                False,
            ),
            hard_delete_enabled=_read_bool(
                config,
                "memory.privacy.hard_delete_enabled",
                False,
            ),
            tombstone_on_forget=_read_bool(
                config,
                "memory.privacy.tombstone_on_forget",
                True,
            ),
            require_policy_approval_for_delete_export=_read_bool(
                config,
                "memory.privacy.require_policy_approval_for_delete_export",
                True,
            ),
        ),
        health=MemoryHealthSettings(
            deep_check_enabled=_read_bool(
                config,
                "memory.health.deep_check_enabled",
                False,
            )
        ),
    )


def get_session_settings(config: ConfigurationView) -> SessionSettings:
    """Resolve typed session settings from validated configuration."""

    return SessionSettings(
        enabled=_read_bool(config, "session.enabled", True),
        identifiers=SessionIdentifierSettings(
            prefix=_read_str(config, "session.identifiers.prefix", "session"),
            accept_client_session_id=_read_bool(
                config,
                "session.identifiers.accept_client_session_id",
                True,
            ),
            generate_when_missing=_read_bool(
                config,
                "session.identifiers.generate_when_missing",
                True,
            ),
            max_length=_read_int(config, "session.identifiers.max_length", 128),
            allowed_pattern=_read_str(
                config,
                "session.identifiers.allowed_pattern",
                r"^[A-Za-z0-9_.:-]{3,128}$",
            ),
        ),
        defaults=SessionDefaultsSettings(
            default_user_id=_read_str(config, "session.defaults.default_user_id", "local_user"),
            default_usecase=_read_optional_str(
                config,
                "session.defaults.default_usecase",
                fallback=_required_str(config, "app.active_usecase"),
            ),
            default_history_limit=_read_int(config, "session.defaults.default_history_limit", 50),
            max_history_limit=_read_int(config, "session.defaults.max_history_limit", 200),
            timezone_metadata_key=_read_str(
                config,
                "session.defaults.timezone_metadata_key",
                "timezone",
            ),
        ),
        lifecycle=SessionLifecycleSettings(
            create_on_first_chat=_read_bool(
                config,
                "session.lifecycle.create_on_first_chat",
                True,
            ),
            resume_existing_sessions=_read_bool(
                config,
                "session.lifecycle.resume_existing_sessions",
                True,
            ),
            reject_unknown_client_session_id=_read_bool(
                config,
                "session.lifecycle.reject_unknown_client_session_id",
                False,
            ),
            update_last_seen_on_load=_read_bool(
                config,
                "session.lifecycle.update_last_seen_on_load",
                True,
            ),
            save_after_failed_orchestration=_read_bool(
                config,
                "session.lifecycle.save_after_failed_orchestration",
                True,
            ),
            save_after_cancelled_stream=_read_bool(
                config,
                "session.lifecycle.save_after_cancelled_stream",
                True,
            ),
        ),
        concurrency=SessionConcurrencySettings(
            mode=_read_str(config, "session.concurrency.mode", "optimistic_version"),
            conflict_policy=_read_str(
                config,
                "session.concurrency.conflict_policy",
                "reject",
            ),
            max_retries=_read_int(config, "session.concurrency.max_retries", 1),
        ),
        state=SessionStateSettings(
            save_on_chat_completion=_read_bool(
                config,
                "session.state.save_on_chat_completion",
                True,
            ),
            save_on_stream_completion=_read_bool(
                config,
                "session.state.save_on_stream_completion",
                True,
            ),
            save_on_stream_cancellation=_read_bool(
                config,
                "session.state.save_on_stream_cancellation",
                True,
            ),
            save_on_stream_failure=_read_bool(
                config,
                "session.state.save_on_stream_failure",
                True,
            ),
            save_each_stream_delta=_read_bool(
                config,
                "session.state.save_each_stream_delta",
                False,
            ),
        ),
        history=SessionHistorySettings(
            enabled=_read_bool(config, "session.history.enabled", False),
            include_tool_summaries=_read_bool(
                config,
                "session.history.include_tool_summaries",
                False,
            ),
            include_system_messages=_read_bool(
                config,
                "session.history.include_system_messages",
                False,
            ),
            include_metadata=_read_bool(config, "session.history.include_metadata", True),
            max_message_chars=_read_int(
                config,
                "session.history.max_message_chars",
                4000,
            ),
            redaction_enabled=_read_bool(
                config,
                "session.history.redaction_enabled",
                True,
            ),
        ),
        management=SessionManagementSettings(
            list_enabled=_read_bool(config, "session.management.list_enabled", False),
            delete_enabled=_read_bool(config, "session.management.delete_enabled", False),
            default_list_limit=_read_int(
                config,
                "session.management.default_list_limit",
                50,
            ),
            max_list_limit=_read_int(
                config,
                "session.management.max_list_limit",
                200,
            ),
        ),
        tracing=SessionTracingSettings(
            record_session_created=_read_bool(
                config,
                "session.tracing.record_session_created",
                True,
            ),
            record_session_resumed=_read_bool(
                config,
                "session.tracing.record_session_resumed",
                True,
            ),
            record_session_reset=_read_bool(
                config,
                "session.tracing.record_session_reset",
                True,
            ),
            record_state_loaded=_read_bool(
                config,
                "session.tracing.record_state_loaded",
                True,
            ),
            record_state_saved=_read_bool(
                config,
                "session.tracing.record_state_saved",
                True,
            ),
            record_history_returned=_read_bool(
                config,
                "session.tracing.record_history_returned",
                True,
            ),
            record_stream_lifecycle=_read_bool(
                config,
                "session.tracing.record_stream_lifecycle",
                True,
            ),
        ),
    )


def build_runtime_redactor(config: ConfigurationView) -> Redactor:
    """Build the runtime redactor from validated observability settings."""

    observability = get_observability_settings(config)
    return Redactor(
        redact_secrets=observability.redact_secrets,
        max_chars=observability.max_trace_payload_chars,
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})

    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)

    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)

    return value


def _unfreeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _unfreeze(item) for key, item in value.items()}

    if isinstance(value, tuple):
        return [_unfreeze(item) for item in value]

    return value


def _read_bool(config: ConfigurationView, path: str, default: bool) -> bool:
    value = config.get(path, default)
    if not isinstance(value, bool):
        raise ConfigurationError(f"Invalid config value at {path}: expected bool.")
    return value


def _read_int(config: ConfigurationView, path: str, default: int) -> int:
    value = config.get(path, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigurationError(f"Invalid config value at {path}: expected int.")
    return value


def _read_str(config: ConfigurationView, path: str, default: str) -> str:
    value = config.get(path, default)
    if not isinstance(value, str):
        raise ConfigurationError(f"Invalid config value at {path}: expected str.")
    return value


def _required_str(config: ConfigurationView, path: str) -> str:
    value = config.require(path)
    if not isinstance(value, str):
        raise ConfigurationError(f"Invalid config value at {path}: expected str.")
    return value


def _read_optional_str(
    config: ConfigurationView,
    path: str,
    *,
    fallback: str,
) -> str:
    value = config.get(path, None)
    if value is None:
        return fallback
    if not isinstance(value, str):
        raise ConfigurationError(f"Invalid config value at {path}: expected str.")
    return value


def _read_optional_str_or_none(config: ConfigurationView, path: str) -> str | None:
    value = config.get(path, None)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"Invalid config value at {path}: expected str.")
    return value


def _read_optional_int(config: ConfigurationView, path: str) -> int | None:
    value = config.get(path, None)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigurationError(f"Invalid config value at {path}: expected int.")
    return value


def _read_optional_bool(config: ConfigurationView, path: str) -> bool | None:
    value = config.get(path, None)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ConfigurationError(f"Invalid config value at {path}: expected bool.")
    return value


def _read_optional_float(config: ConfigurationView, path: str) -> float | None:
    value = config.get(path, None)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigurationError(f"Invalid config value at {path}: expected float.")
    return float(value)


def _read_float(config: ConfigurationView, path: str, default: float) -> float:
    value = config.get(path, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigurationError(f"Invalid config value at {path}: expected float.")
    return float(value)


def _read_str_tuple(
    config: ConfigurationView,
    path: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    value = config.get(path, default)
    if isinstance(value, tuple):
        items = value
    elif isinstance(value, list):
        items = tuple(value)
    else:
        raise ConfigurationError(f"Invalid config value at {path}: expected list[str].")

    if not all(isinstance(item, str) for item in items):
        raise ConfigurationError(f"Invalid config value at {path}: expected list[str].")

    return cast(tuple[str, ...], items)


def _read_str_mapping(config: ConfigurationView, path: str) -> dict[str, str]:
    value = config.get(path, {})
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"Invalid config value at {path}: expected dict[str, str].")

    result: dict[str, str] = {}
    for item_key, item_value in value.items():
        if not isinstance(item_key, str) or not isinstance(item_value, str):
            raise ConfigurationError(
                f"Invalid config value at {path}: expected dict[str, str]."
            )
        result[item_key] = item_value
    return result


def _read_mapping_section(
    config: ConfigurationView,
    *,
    primary_path: str,
    fallback_path: str,
) -> Mapping[str, Any]:
    value = config.get(primary_path, None)
    resolved_path = primary_path
    if value is None:
        value = config.get(fallback_path, {})
        resolved_path = fallback_path

    if not isinstance(value, Mapping):
        raise ConfigurationError(
            f"Invalid config value at {resolved_path}: expected mapping."
        )
    return value


def _read_agent_plugin_sections(config: ConfigurationView) -> Mapping[str, Any]:
    value = config.get("agents.plugins", None)
    resolved_path = "agents.plugins"
    if value is None:
        value = config.get("agents", {})
        resolved_path = "agents"

    if not isinstance(value, Mapping):
        raise ConfigurationError(
            f"Invalid config value at {resolved_path}: expected mapping."
        )

    if resolved_path == "agents":
        return {
            key: item
            for key, item in value.items()
            if isinstance(key, str) and key not in {"defaults", "plugins"}
        }

    return value


def _read_agent_plugin_compatibility_value(
    current: Mapping[str, Any],
    part: str,
) -> Any | None:
    plugins = current.get("plugins")
    if not isinstance(plugins, Mapping):
        return None
    if part in {"defaults", "plugins"}:
        return None
    return plugins.get(part)


def _normalize_strategy_type(value: str, *, path: str) -> str:
    normalized = value.strip().lower()
    if normalized == "direct":
        normalized = "direct_agent"

    if normalized not in {
        "echo",
        "direct_agent",
        "retrieval_augmented",
        "tool_assisted",
        "router",
        "bounded_planner",
        "memory_update",
        "fallback_answer",
    }:
        raise ConfigurationError(
            f"Invalid config value at {path}: unsupported strategy type '{value}'."
        )
    return normalized


def _read_mapping_dict(config: ConfigurationView, path: str) -> dict[str, Any]:
    value = config.get(path, {})
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"Invalid config value at {path}: expected mapping.")
    return cast(dict[str, Any], _unfreeze(value))


def _read_optional_mapping_dict(
    config: ConfigurationView,
    path: str,
) -> dict[str, Any] | None:
    value = config.get(path, None)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"Invalid config value at {path}: expected mapping.")
    return cast(dict[str, Any], _unfreeze(value))


def _read_memory_base_dir(config: ConfigurationView) -> Path:
    configured = config.get("persistence.base_dir")
    if isinstance(configured, str) and configured.strip():
        return resolve_backend_path(configured.strip())

    app_data_dir = config.get("app.data_dir")
    if isinstance(app_data_dir, str) and app_data_dir.strip():
        return resolve_backend_path(app_data_dir.strip())

    return resolve_backend_path("data")


def _read_optional_resolved_path(
    config: ConfigurationView,
    path: str,
    *,
    resolve_with: "Callable[[str], Path]",
) -> Path | None:
    value = config.get(path, None)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigurationError(f"Invalid config value at {path}: expected str.")

    normalized = value.strip()
    if not normalized:
        return None
    return resolve_with(normalized)


def _read_resolved_backend_path(
    config: ConfigurationView,
    path: str,
    *,
    default: str,
) -> Path:
    value = _read_str(config, path, default).strip()
    if not value:
        raise ConfigurationError(f"Invalid config value at {path}: expected non-empty str.")
    return resolve_backend_path(value)