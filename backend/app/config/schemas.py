"""Strict Pydantic models for backend runtime configuration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class StoreConfig(StrictConfigModel):
    provider: str
    path: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class PersistenceConfig(StrictConfigModel):
    workflow_state: StoreConfig
    trace: StoreConfig
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


class BackendConfig(StrictConfigModel):
    app: AppConfig
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