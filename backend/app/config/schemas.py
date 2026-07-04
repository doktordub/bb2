"""Strict Pydantic models for backend runtime configuration."""

from __future__ import annotations

from collections.abc import Mapping
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
_ALLOWED_SESSION_CONCURRENCY_MODES = frozenset({"optimistic_version"})
_ALLOWED_SESSION_CONFLICT_POLICIES = frozenset({"reject"})
_ALLOWED_LLM_PROVIDER_TYPES = frozenset(
    {"custom_http", "fake", "google", "openai", "openai_compatible"}
)
_ALLOWED_MCP_TRANSPORTS = frozenset({"http", "sse", "websocket"})
_ALLOWED_MCP_AUTH_MODES = frozenset(
    {"none", "bearer", "jwt", "oauth_client_credentials"}
)
_ALLOWED_MEMORY_PROVIDER_TYPES = frozenset({"disabled", "fake", "memory_store", "none"})
_ALLOWED_MEMORY_DEFAULT_SCOPES = frozenset({"project", "user"})
_ALLOWED_MEMORY_DIMENSION_MISMATCH_POLICIES = frozenset(
    {"error", "quarantine", "reembed"}
)
_ALLOWED_MEMORY_REMOVED_CHUNK_POLICIES = frozenset({"hard_delete", "mark_removed"})
_ALLOWED_MEMORY_SENSITIVITY_LEVELS = frozenset(
    {"internal", "private", "public", "sensitive"}
)
_ALLOWED_DEPLOYMENT_PROFILES = frozenset({"local", "test", "staging", "production"})
_ALLOWED_POLICY_MODES = frozenset({"enforce", "report_only"})
_ALLOWED_POLICY_DEFAULT_DECISIONS = frozenset({"allow", "deny"})
_ALLOWED_ORCHESTRATION_STRATEGY_TYPES = frozenset(
    {
        "echo",
        "direct_agent",
        "retrieval_augmented",
        "tool_assisted",
        "router",
        "bounded_planner",
        "memory_update",
        "fallback_answer",
    }
)
_ALLOWED_AGENT_TYPES = frozenset(
    {
        "general_assistant",
        "document_qa",
        "tool_using",
        "project_agent",
        "memory_curator",
        "reviewer",
        "custom",
    }
)
_ALLOWED_AGENT_MEMORY_SCOPES = frozenset(
    {
        "agent",
        "document",
        "global",
        "project",
        "session",
        "source",
        "tenant",
        "usecase",
        "user",
    }
)
_ALLOWED_MCP_ENDPOINT_SCHEMES = frozenset({"http", "https", "ws", "wss"})
_ALLOWED_JSON_SCHEMA_TYPES = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)
_ALLOWED_TOOL_SAFETY_LEVELS = frozenset(
    {"read_only", "write", "destructive", "external_side_effect"}
)
_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_HTTP_METHOD_PATTERN = re.compile(r"^[A-Z]+$")
_SESSION_ID_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")


class StrictConfigModel(BaseModel):
    """Base model for strict configuration parsing."""

    model_config = ConfigDict(extra="forbid")


class AppConfig(StrictConfigModel):
    name: str
    environment: str = "local"
    active_usecase: str
    data_dir: str = "./data"

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_DEPLOYMENT_PROFILES:
            supported = ", ".join(sorted(_ALLOWED_DEPLOYMENT_PROFILES))
            raise ValueError(f"environment must be one of: {supported}")
        return normalized


class FeatureConfig(StrictConfigModel):
    streaming_enabled: bool = True
    memory_enabled: bool = True
    tools_enabled: bool = True
    trace_enabled: bool = True


class UseCaseMemoryConfig(StrictConfigModel):
    enabled: bool = True
    include_document_chunks: bool = True
    default_limit: int = Field(default=10, ge=1, le=100)
    allowed_project_ids: list[str] = Field(default_factory=list)
    default_project_id: str | None = None

    @field_validator("allowed_project_ids")
    @classmethod
    def normalize_allowed_project_ids(cls, value: list[str]) -> list[str]:
        return _normalize_name_list(value, field_name="allowed_project_ids")

    @field_validator("default_project_id")
    @classmethod
    def normalize_default_project_id(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_default_project_id(self) -> "UseCaseMemoryConfig":
        if (
            self.default_project_id is not None
            and self.allowed_project_ids
            and self.default_project_id not in self.allowed_project_ids
        ):
            raise ValueError(
                "default_project_id must be one of allowed_project_ids when an allowlist is configured"
            )
        return self


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
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategyConfig(StrictConfigModel):
    enabled: bool = True
    type: str
    description: str | None = None
    llm_profile: str | None = None
    max_candidate_agents: int | None = Field(default=None, ge=1, le=20)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def normalize_strategy_type(cls, value: str) -> str:
        return _normalize_orchestration_strategy_type(value)


class OrchestrationConversationContextConfig(StrictConfigModel):
    enabled: bool = False
    mode: str = "window"
    max_messages: int = Field(default=12, ge=1, le=200)
    max_chars: int = Field(default=12000, ge=256, le=200000)
    include_assistant_messages: bool = True
    summary_threshold_messages: int = Field(default=24, ge=1, le=500)
    summary_max_chars: int = Field(default=2000, ge=128, le=40000)

    @field_validator("mode")
    @classmethod
    def normalize_mode(cls, value: str) -> str:
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        allowed = {"window", "summary_then_window"}
        if normalized not in allowed:
            supported = ", ".join(sorted(allowed))
            raise ValueError(f"mode must be one of: {supported}")
        return normalized

    @model_validator(mode="after")
    def validate_summary_threshold(self) -> "OrchestrationConversationContextConfig":
        if self.summary_threshold_messages < self.max_messages:
            raise ValueError(
                "summary_threshold_messages must be greater than or equal to max_messages"
            )
        return self


class OrchestrationDefaultsConfig(StrictConfigModel):
    strategy: str | None = None
    fallback_strategy: str | None = None
    max_steps: int = Field(default=8, ge=1, le=100)
    max_tool_calls: int = Field(default=4, ge=1, le=100)
    max_memory_searches: int = Field(default=3, ge=1, le=100)
    max_memory_writes: int = Field(default=1, ge=1, le=100)
    max_llm_calls: int = Field(default=6, ge=1, le=100)
    max_tool_loop_iterations: int = Field(default=3, ge=1, le=100)
    max_context_bytes: int = Field(default=64000, ge=1, le=10485760)
    max_turn_duration_seconds: int = Field(default=120, ge=1, le=3600)
    max_stream_duration_seconds: int = Field(default=300, ge=1, le=3600)
    emit_step_events: bool = True
    emit_tool_events: bool = True
    emit_memory_events: bool = True
    stream_strategy_events: bool = True
    expose_strategy_metadata: bool = True
    expose_chain_of_thought: bool = False
    save_runtime_snapshots: bool = False
    conversation_context: OrchestrationConversationContextConfig = Field(
        default_factory=OrchestrationConversationContextConfig
    )

    @model_validator(mode="after")
    def validate_durations(self) -> "OrchestrationDefaultsConfig":
        if self.max_stream_duration_seconds < self.max_turn_duration_seconds:
            raise ValueError(
                "max_stream_duration_seconds must be greater than or equal to "
                "max_turn_duration_seconds"
            )
        return self


class OrchestrationStrategyMemoryConfig(StrictConfigModel):
    default_limit: int = Field(default=10, ge=1, le=100)
    include_document_chunks: bool = True
    include_user_memory: bool = True
    min_score: float | None = Field(default=None, ge=0.0, le=1.0)
    max_context_items: int | None = Field(default=None, ge=1, le=100)
    max_context_bytes: int | None = Field(default=None, ge=1, le=10485760)


class OrchestrationStrategyToolsConfig(StrictConfigModel):
    max_calls: int | None = Field(default=None, ge=1, le=100)
    max_tool_loop_iterations: int | None = Field(default=None, ge=1, le=100)
    allowed_safety_levels: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    stream_tool_events: bool = True

    @field_validator("allowed_safety_levels")
    @classmethod
    def normalize_allowed_safety_levels(cls, value: list[str]) -> list[str]:
        normalized = _normalize_name_list(
            value,
            field_name="allowed_safety_levels",
        )
        invalid = sorted(
            set(normalized) - set(_ALLOWED_TOOL_SAFETY_LEVELS)
        )
        if invalid:
            supported = ", ".join(sorted(_ALLOWED_TOOL_SAFETY_LEVELS))
            raise ValueError(
                "allowed_safety_levels must only contain supported values: "
                f"{supported}"
            )
        return normalized

    @field_validator("allowed_tools")
    @classmethod
    def normalize_allowed_tools(cls, value: list[str]) -> list[str]:
        return _normalize_name_list(value, field_name="allowed_tools")


class OrchestrationStrategyConfig(StrictConfigModel):
    enabled: bool = True
    type: str
    description: str | None = None
    default_agent: str | None = None
    allowed_usecases: list[str] = Field(default_factory=list)
    llm_profile: str | None = None
    planner_llm_profile: str | None = None
    executor_llm_profile: str | None = None
    memory_enabled: bool = False
    memory_write_enabled: bool = False
    tools_enabled: bool = False
    max_steps: int | None = Field(default=None, ge=1, le=100)
    max_tool_calls: int | None = Field(default=None, ge=1, le=100)
    max_memory_searches: int | None = Field(default=None, ge=1, le=100)
    max_memory_writes: int | None = Field(default=None, ge=1, le=100)
    max_llm_calls: int | None = Field(default=None, ge=1, le=100)
    max_tool_loop_iterations: int | None = Field(default=None, ge=1, le=100)
    max_context_bytes: int | None = Field(default=None, ge=1, le=10485760)
    max_plan_steps: int | None = Field(default=None, ge=1, le=100)
    max_execute_steps: int | None = Field(default=None, ge=1, le=100)
    max_candidate_agents: int | None = Field(default=None, ge=1, le=20)
    candidate_limit: int | None = Field(default=None, ge=1, le=100)
    candidate_strategies: list[str] = Field(default_factory=list)
    fallback_strategy: str | None = None
    require_policy_approval: bool = False
    stream_llm_deltas: bool = True
    stream_tool_events: bool = True
    stream_strategy_events: bool | None = None
    expose_strategy_metadata: bool = True
    message: str | None = None
    memory: OrchestrationStrategyMemoryConfig = Field(
        default_factory=OrchestrationStrategyMemoryConfig
    )
    tools: OrchestrationStrategyToolsConfig = Field(
        default_factory=OrchestrationStrategyToolsConfig
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def normalize_strategy_type(cls, value: str) -> str:
        return _normalize_orchestration_strategy_type(value)

    @field_validator("allowed_usecases", "candidate_strategies")
    @classmethod
    def normalize_name_lists(cls, value: list[str], info: Any) -> list[str]:
        return _normalize_name_list(value, field_name=str(info.field_name))


class OrchestrationUseCaseConfig(StrictConfigModel):
    enabled: bool = True
    display_name: str | None = None
    description: str | None = None
    strategy: str
    agent: str | None = None
    llm_profile: str | None = None
    allowed_agents: list[str] = Field(default_factory=list)
    allowed_strategies: list[str] = Field(default_factory=list)
    policy_profile: str = "default"
    memory: UseCaseMemoryConfig = Field(default_factory=UseCaseMemoryConfig)
    tools: UseCaseToolConfig = Field(default_factory=UseCaseToolConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("allowed_agents", "allowed_strategies")
    @classmethod
    def normalize_allowed_agents(cls, value: list[str], info: Any) -> list[str]:
        return _normalize_name_list(value, field_name=str(info.field_name))


class OrchestrationConfig(StrictConfigModel):
    enabled: bool = True
    defaults: OrchestrationDefaultsConfig = Field(
        default_factory=OrchestrationDefaultsConfig
    )
    strategies: dict[str, OrchestrationStrategyConfig] = Field(default_factory=dict)
    usecases: dict[str, OrchestrationUseCaseConfig] = Field(default_factory=dict)


class AgentCapabilityConfig(StrictConfigModel):
    answer: bool = True
    review: bool = False
    stream: bool = True
    memory_read: bool = False
    memory_write: bool = False
    memory_candidate_extract: bool = False
    tool_intents: bool = False
    tool_execute: bool = False
    self_managed_memory: bool = False
    self_managed_tools: bool = False


class AgentLimitConfig(StrictConfigModel):
    max_prompt_context_bytes: int = Field(default=32000, ge=1, le=10485760)
    max_output_chars: int = Field(default=12000, ge=1, le=200000)
    max_tool_intents: int = Field(default=3, ge=0, le=100)
    max_memory_candidates: int = Field(default=5, ge=0, le=100)
    max_llm_calls: int = Field(default=1, ge=1, le=100)
    max_self_managed_tool_calls: int = Field(default=0, ge=0, le=100)
    max_self_managed_memory_searches: int = Field(default=0, ge=0, le=100)


class AgentContextPolicyConfig(StrictConfigModel):
    require_context_for_grounded_claims: bool = False
    cite_context_labels: bool = True
    max_context_items: int = Field(default=8, ge=1, le=100)
    max_context_bytes: int = Field(default=32000, ge=1, le=10485760)
    allow_untrusted_context_instructions: bool = False


class AgentDefaultsConfig(StrictConfigModel):
    enabled: bool = True
    stream_llm_deltas: bool = True
    expose_agent_metadata: bool = True
    strict_prompt_profile_validation: bool = False
    known_prompt_profiles: list[str] = Field(default_factory=list)
    max_prompt_context_bytes: int = Field(default=32000, ge=1, le=10485760)
    max_output_chars: int = Field(default=12000, ge=1, le=200000)
    max_tool_intents: int = Field(default=3, ge=0, le=100)
    max_memory_candidates: int = Field(default=5, ge=0, le=100)
    max_llm_calls: int = Field(default=1, ge=1, le=100)
    max_self_managed_tool_calls: int = Field(default=0, ge=0, le=100)
    max_self_managed_memory_searches: int = Field(default=0, ge=0, le=100)
    allow_self_managed_tools: bool = False
    allow_self_managed_memory: bool = False
    allow_memory_write: bool = False

    @field_validator("known_prompt_profiles")
    @classmethod
    def normalize_known_prompt_profiles(cls, value: list[str]) -> list[str]:
        return _normalize_name_list(value, field_name="known_prompt_profiles")


class AgentMemoryConfig(StrictConfigModel):
    search_enabled: bool = True
    write_enabled: bool = False
    allowed_project_ids: list[str] = Field(default_factory=list)
    default_project_id: str | None = None

    @field_validator("allowed_project_ids")
    @classmethod
    def normalize_allowed_project_ids(cls, value: list[str]) -> list[str]:
        return _normalize_name_list(value, field_name="allowed_project_ids")

    @field_validator("default_project_id")
    @classmethod
    def normalize_default_project_id(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_default_project_id(self) -> "AgentMemoryConfig":
        if (
            self.default_project_id is not None
            and self.allowed_project_ids
            and self.default_project_id not in self.allowed_project_ids
        ):
            raise ValueError(
                "default_project_id must be one of allowed_project_ids when an allowlist is configured"
            )
        return self


class AgentPromptConfig(StrictConfigModel):
    system_prompt: str | None = None
    developer_prompt: str | None = None


class AgentConfig(StrictConfigModel):
    enabled: bool = True
    type: str = "custom"
    display_name: str | None = None
    description: str | None = None
    llm_profile: str | None = None
    prompt_profile: str | None = None
    capabilities: AgentCapabilityConfig = Field(default_factory=AgentCapabilityConfig)
    limits: AgentLimitConfig = Field(default_factory=AgentLimitConfig)
    context_policy: AgentContextPolicyConfig = Field(
        default_factory=AgentContextPolicyConfig
    )
    allowed_tool_intents: list[str] = Field(default_factory=list)
    allowed_memory_scopes: list[str] = Field(default_factory=list)
    expose_metadata: bool = True
    stream_llm_deltas: bool = True
    module: str | None = None
    class_name: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    memory: AgentMemoryConfig = Field(default_factory=AgentMemoryConfig)
    prompts: AgentPromptConfig = Field(default_factory=AgentPromptConfig)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        data = dict(value)
        if not _has_non_blank_value(_read_mapping_value_as_str(data, "type")):
            if _read_mapping_value_as_str(data, "module") or _read_mapping_value_as_str(
                data,
                "class_name",
            ):
                data["type"] = "custom"
            else:
                data["type"] = "general_assistant"

        if not isinstance(data.get("capabilities"), Mapping):
            data["capabilities"] = _translate_legacy_agent_capabilities(data)

        if "allowed_tool_intents" not in data and isinstance(data.get("allowed_tools"), list):
            data["allowed_tool_intents"] = list(data.get("allowed_tools", []))

        if "allowed_tools" not in data and isinstance(data.get("allowed_tool_intents"), list):
            data["allowed_tools"] = list(data.get("allowed_tool_intents", []))

        memory = data.get("memory")
        if not isinstance(memory, Mapping):
            capabilities = data.get("capabilities")
            capabilities_mapping = capabilities if isinstance(capabilities, Mapping) else {}
            data["memory"] = {
                "search_enabled": bool(capabilities_mapping.get("memory_read", False)),
                "write_enabled": bool(capabilities_mapping.get("memory_write", False)),
            }

        return data

    @field_validator(
        "display_name",
        "description",
        "llm_profile",
        "prompt_profile",
        "module",
        "class_name",
    )
    @classmethod
    def normalize_optional_fields(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("type")
    @classmethod
    def normalize_agent_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_AGENT_TYPES:
            supported = ", ".join(sorted(_ALLOWED_AGENT_TYPES))
            raise ValueError(f"type must be one of: {supported}")
        return normalized

    @field_validator("allowed_tool_intents", "allowed_tools")
    @classmethod
    def normalize_allowed_tool_lists(cls, value: list[str], info: Any) -> list[str]:
        return _normalize_name_list(value, field_name=str(info.field_name))

    @field_validator("allowed_memory_scopes")
    @classmethod
    def normalize_allowed_memory_scopes(cls, value: list[str]) -> list[str]:
        normalized = _normalize_name_list(value, field_name="allowed_memory_scopes")
        invalid = sorted(set(normalized) - set(_ALLOWED_AGENT_MEMORY_SCOPES))
        if invalid:
            supported = ", ".join(sorted(_ALLOWED_AGENT_MEMORY_SCOPES))
            raise ValueError(
                "allowed_memory_scopes must only contain supported values: "
                f"{supported}"
            )
        return normalized

    @model_validator(mode="after")
    def validate_custom_requirements(self) -> "AgentConfig":
        if self.type == "custom":
            if not _has_non_blank_value(self.module):
                raise ValueError("custom agents require module")
            if not _has_non_blank_value(self.class_name):
                raise ValueError("custom agents require class_name")
        return self


class AgentsConfig(StrictConfigModel):
    defaults: AgentDefaultsConfig = Field(default_factory=AgentDefaultsConfig)
    plugins: dict[str, AgentConfig] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_agents(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        data = dict(value)
        raw_defaults = data.get("defaults")
        defaults = dict(raw_defaults) if isinstance(raw_defaults, Mapping) else {}
        plugins = _mapping_to_dict_of_mappings(data.get("plugins"))

        for raw_key, raw_value in data.items():
            if raw_key in {"defaults", "plugins"}:
                continue
            if isinstance(raw_key, str) and isinstance(raw_value, Mapping):
                legacy_plugin = _translate_legacy_agent_to_plugin(raw_value)
                plugins[raw_key] = _merge_nested_mappings(
                    legacy_plugin,
                    plugins.get(raw_key, {}),
                )

        normalized_plugins: dict[str, dict[str, Any]] = {}
        for plugin_name, plugin_section in plugins.items():
            normalized_plugins[plugin_name] = _apply_agent_defaults(
                defaults,
                plugin_section,
            )

        return {
            "defaults": defaults,
            "plugins": normalized_plugins,
        }


class LLMDefaultsConfig(StrictConfigModel):
    profile: str
    timeout_seconds: int = Field(default=120, ge=1, le=600)
    stream_timeout_seconds: int = Field(default=300, ge=1, le=600)
    max_retries: int = Field(default=1, ge=0, le=10)
    trace_prompts: bool = False
    trace_completions: bool = False

    @model_validator(mode="after")
    def validate_timeouts(self) -> "LLMDefaultsConfig":
        if self.stream_timeout_seconds < self.timeout_seconds:
            raise ValueError(
                "stream_timeout_seconds must be greater than or equal to "
                "timeout_seconds"
            )
        return self


class LLMProviderConfig(StrictConfigModel):
    type: str
    enabled: bool = True
    base_url: str | None = None
    endpoint: str | None = None
    api_key: str | None = None
    auth_header: str | None = None
    auth_token: str | None = None
    timeout_seconds: int = Field(default=120, ge=1, le=600)
    stream_timeout_seconds: int = Field(default=300, ge=1, le=600)
    headers: dict[str, str] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        data = dict(value)
        legacy_headers = data.pop("default_headers", None)
        headers = data.get("headers")
        if headers is None:
            data["headers"] = legacy_headers or {}
        elif isinstance(headers, Mapping) and isinstance(legacy_headers, Mapping):
            merged_headers = dict(legacy_headers)
            merged_headers.update(headers)
            data["headers"] = merged_headers
        return data

    @field_validator("type")
    @classmethod
    def normalize_provider_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_LLM_PROVIDER_TYPES:
            supported = ", ".join(sorted(_ALLOWED_LLM_PROVIDER_TYPES))
            raise ValueError(f"type must be one of: {supported}")
        return normalized

    @field_validator("base_url", "endpoint")
    @classmethod
    def normalize_optional_http_url(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if normalized == "":
            return None

        parsed = urlsplit(normalized)
        if parsed.scheme not in _ALLOWED_CORS_ORIGIN_SCHEMES or parsed.netloc == "":
            raise ValueError("must be a valid http or https URL")
        return normalized

    @field_validator("auth_header")
    @classmethod
    def normalize_optional_header_name(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if normalized == "":
            return None
        if not _HEADER_NAME_PATTERN.fullmatch(normalized):
            raise ValueError("must be a valid HTTP header name")
        return normalized

    @model_validator(mode="after")
    def validate_runtime_requirements(self) -> "LLMProviderConfig":
        if self.stream_timeout_seconds < self.timeout_seconds:
            raise ValueError(
                "stream_timeout_seconds must be greater than or equal to "
                "timeout_seconds"
            )

        if self.enabled and self.type == "openai_compatible" and self.base_url is None:
            raise ValueError("enabled openai_compatible providers require base_url")

        if self.enabled and self.type == "custom_http" and self.endpoint is None:
            raise ValueError("enabled custom_http providers require endpoint")

        if self.enabled and self.type in {"openai", "google"} and not _has_non_blank_value(
            self.api_key
        ):
            raise ValueError(
                f"enabled {self.type} providers require a non-empty api_key"
            )

        if self.auth_header is None and self.auth_token is not None:
            raise ValueError("auth_token requires auth_header")

        if self.auth_header is not None and self.auth_token is None:
            raise ValueError("auth_header requires auth_token")

        return self


class LLMProfileAllowlistConfig(StrictConfigModel):
    usecases: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)

    @field_validator("usecases", "agents", "strategies")
    @classmethod
    def normalize_members(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            stripped = item.strip()
            if stripped == "":
                raise ValueError("allowlist entries must not be empty")
            if stripped not in seen:
                normalized.append(stripped)
                seen.add(stripped)
        return normalized


class LLMProfileConfig(StrictConfigModel):
    enabled: bool = True
    provider: str
    model: str
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_total_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    stream_timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    supports_streaming: bool = True
    supports_json_schema: bool = False
    supports_tool_calling: bool = False
    allowed_for: LLMProfileAllowlistConfig = Field(default_factory=LLMProfileAllowlistConfig)
    fallback_profiles: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        data = dict(value)
        if "max_output_tokens" not in data and "max_tokens" in data:
            data["max_output_tokens"] = data.pop("max_tokens")
        if "extra" not in data and "metadata" in data:
            data["extra"] = data.pop("metadata")
        return data

    @field_validator("model")
    @classmethod
    def normalize_model_name(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("model must not be empty")
        return normalized

    @field_validator("fallback_profiles")
    @classmethod
    def normalize_fallback_profiles(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            stripped = item.strip()
            if stripped == "":
                raise ValueError("fallback profile names must not be empty")
            if stripped not in seen:
                normalized.append(stripped)
                seen.add(stripped)
        return normalized

    @model_validator(mode="after")
    def validate_limits(self) -> "LLMProfileConfig":
        if (
            self.stream_timeout_seconds is not None
            and self.timeout_seconds is not None
            and self.stream_timeout_seconds < self.timeout_seconds
        ):
            raise ValueError(
                "stream_timeout_seconds must be greater than or equal to "
                "timeout_seconds"
            )

        if (
            self.max_total_tokens is not None
            and self.max_input_tokens is not None
            and self.max_total_tokens < self.max_input_tokens
        ):
            raise ValueError(
                "max_total_tokens must be greater than or equal to max_input_tokens"
            )

        if (
            self.max_total_tokens is not None
            and self.max_output_tokens is not None
            and self.max_total_tokens < self.max_output_tokens
        ):
            raise ValueError(
                "max_total_tokens must be greater than or equal to max_output_tokens"
            )

        return self


class LLMConfig(StrictConfigModel):
    defaults: LLMDefaultsConfig
    providers: dict[str, LLMProviderConfig]
    profiles: dict[str, LLMProfileConfig]

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_defaults(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        data = dict(value)
        defaults_raw = data.get("defaults")
        defaults = dict(defaults_raw) if isinstance(defaults_raw, Mapping) else {}

        legacy_default_profile = data.pop("default_profile", None)
        if legacy_default_profile is not None and "profile" not in defaults:
            defaults["profile"] = legacy_default_profile

        data["defaults"] = defaults
        return data

    @property
    def default_profile(self) -> str:
        return self.defaults.profile


class ToolingDefaultsConfig(StrictConfigModel):
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    stream_timeout_seconds: int = Field(default=300, ge=1, le=600)
    max_retries: int = Field(default=1, ge=0, le=10)
    max_argument_bytes: int = Field(default=65536, ge=1, le=1048576)
    max_result_bytes: int = Field(default=262144, ge=1, le=10485760)
    trace_arguments: bool = False
    trace_results: bool = False
    discovery_on_startup: bool = True
    discovery_refresh_seconds: int = Field(default=300, ge=1, le=86400)

    @model_validator(mode="after")
    def validate_timeouts(self) -> "ToolingDefaultsConfig":
        if self.stream_timeout_seconds < self.timeout_seconds:
            raise ValueError(
                "stream_timeout_seconds must be greater than or equal to "
                "timeout_seconds"
            )
        return self


class MCPOAuthConfig(StrictConfigModel):
    token_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scopes: list[str] = Field(default_factory=list)

    @field_validator("token_url")
    @classmethod
    def normalize_token_url(cls, value: str | None) -> str | None:
        return _normalize_optional_url_value(
            value,
            allowed_schemes=_ALLOWED_CORS_ORIGIN_SCHEMES,
        )

    @field_validator("client_id", "client_secret")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("scopes")
    @classmethod
    def normalize_scopes(cls, value: list[str]) -> list[str]:
        return _normalize_name_list(value, field_name="scopes")


class MCPAuthConfig(StrictConfigModel):
    mode: str = "none"
    token: str | None = None
    jwt: str | None = None
    oauth: MCPOAuthConfig = Field(default_factory=MCPOAuthConfig)

    @model_validator(mode="before")
    @classmethod
    def normalize_oauth_aliases(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        data = dict(value)
        oauth_raw = data.get("oauth")
        oauth = dict(oauth_raw) if isinstance(oauth_raw, Mapping) else {}
        for key in ("token_url", "client_id", "client_secret", "scopes"):
            if key in data and key not in oauth:
                oauth[key] = data.pop(key)
        if oauth:
            data["oauth"] = oauth
        return data

    @field_validator("mode")
    @classmethod
    def normalize_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_MCP_AUTH_MODES:
            supported = ", ".join(sorted(_ALLOWED_MCP_AUTH_MODES))
            raise ValueError(f"mode must be one of: {supported}")
        return normalized

    @field_validator("token", "jwt")
    @classmethod
    def normalize_optional_secret_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class MCPServerConfig(StrictConfigModel):
    name: str = "main"
    enabled: bool = True
    url: str | None = None
    transport: str = "http"
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    stream_timeout_seconds: int = Field(default=300, ge=1, le=600)
    auth: MCPAuthConfig = Field(default_factory=MCPAuthConfig)
    tool_discovery_enabled: bool = True

    @model_validator(mode="before")
    @classmethod
    def normalize_endpoint_alias(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        data = dict(value)
        endpoint = data.pop("endpoint", None)
        current_url = data.get("url")
        normalized_endpoint = _normalize_optional_text(endpoint)
        normalized_url = _normalize_optional_text(current_url)

        if normalized_url is None and normalized_endpoint is not None:
            data["url"] = normalized_endpoint
        elif normalized_endpoint is not None and normalized_url is not None:
            if normalized_endpoint != normalized_url:
                raise ValueError("endpoint and url must match when both are configured")
            data["url"] = normalized_url

        return data

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("name must not be empty")
        return normalized

    @field_validator("url")
    @classmethod
    def normalize_optional_endpoint(cls, value: str | None) -> str | None:
        return _normalize_optional_url_value(
            value,
            allowed_schemes=_ALLOWED_MCP_ENDPOINT_SCHEMES,
        )

    @field_validator("transport")
    @classmethod
    def normalize_transport(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_MCP_TRANSPORTS:
            supported = ", ".join(sorted(_ALLOWED_MCP_TRANSPORTS))
            raise ValueError(f"transport must be one of: {supported}")
        return normalized

    @model_validator(mode="after")
    def validate_runtime_requirements(self) -> "MCPServerConfig":
        if self.stream_timeout_seconds < self.timeout_seconds:
            raise ValueError(
                "stream_timeout_seconds must be greater than or equal to "
                "timeout_seconds"
            )

        if self.enabled:
            if self.url is None:
                raise ValueError("enabled MCP servers require endpoint or url")
            _validate_mcp_auth_requirements(self.auth)

        return self


class MCPConfig(StrictConfigModel):
    main: MCPServerConfig


class ToolAllowedForConfig(StrictConfigModel):
    usecases: list[str] = Field(default_factory=list)
    agents: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)

    @field_validator("usecases", "agents", "strategies")
    @classmethod
    def normalize_members(cls, value: list[str]) -> list[str]:
        return _normalize_name_list(value, field_name="allowed_for")


class ToolDefinitionConfig(StrictConfigModel):
    enabled: bool = True
    mcp_tool_name: str
    description: str | None = None
    allowed_for: ToolAllowedForConfig = Field(default_factory=ToolAllowedForConfig)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    max_argument_bytes: int | None = Field(default=None, ge=1, le=1048576)
    max_result_bytes: int | None = Field(default=None, ge=1, le=10485760)
    approval_required: bool = False
    input_schema_override: dict[str, Any] | None = None
    output_schema_override: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)
    safety_level: str = "read_only"
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_safety_defaults(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        data = dict(value)
        safety_level = data.get("safety_level", "read_only")
        if isinstance(safety_level, str) and "enabled" not in data:
            if safety_level.strip().lower() in {"destructive", "external_side_effect"}:
                data["enabled"] = False
        return data

    @field_validator("mcp_tool_name")
    @classmethod
    def normalize_mcp_tool_name(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("mcp_tool_name must not be empty")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_optional_description(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return _normalize_name_list(value, field_name="tags")

    @field_validator("safety_level")
    @classmethod
    def normalize_safety_level(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_TOOL_SAFETY_LEVELS:
            supported = ", ".join(sorted(_ALLOWED_TOOL_SAFETY_LEVELS))
            raise ValueError(f"safety_level must be one of: {supported}")
        return normalized

    @field_validator("input_schema_override", "output_schema_override")
    @classmethod
    def validate_schema_overrides(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        _validate_json_schema_object(value)
        return dict(value)


class ToolRegistryConfig(StrictConfigModel):
    allow_discovered_tools: bool = True
    require_configured_allowlist: bool = True
    tools: dict[str, ToolDefinitionConfig] = Field(default_factory=dict)

    @field_validator("tools")
    @classmethod
    def normalize_tool_names(
        cls,
        value: dict[str, ToolDefinitionConfig],
    ) -> dict[str, ToolDefinitionConfig]:
        normalized: dict[str, ToolDefinitionConfig] = {}
        for key, item in value.items():
            stripped = key.strip()
            if stripped == "":
                raise ValueError("tool names must not be empty")
            if stripped in normalized:
                raise ValueError("tool names must be unique")
            normalized[stripped] = item
        return normalized


class ToolingConfig(StrictConfigModel):
    enabled: bool = False
    defaults: ToolingDefaultsConfig = Field(default_factory=ToolingDefaultsConfig)
    registry: ToolRegistryConfig = Field(default_factory=ToolRegistryConfig)


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
    memory: StoreConfig = Field(
        default_factory=lambda: StoreConfig(provider="memory_store", required=False)
    )


class MemoryDefaultsConfig(StrictConfigModel):
    default_scope: str = "project"
    top_k: int = Field(default=10, ge=1, le=100)
    include_agent_memories: bool = True
    include_document_chunks: bool = True
    include_graph_context: bool = True
    max_result_chars: int = Field(default=1200, ge=1)
    max_total_context_chars: int = Field(default=8000, ge=1)
    trace_query_capture: str = "none"
    trace_result_content_capture: str = "none"

    @field_validator("default_scope")
    @classmethod
    def normalize_default_scope(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_MEMORY_DEFAULT_SCOPES:
            supported = ", ".join(sorted(_ALLOWED_MEMORY_DEFAULT_SCOPES))
            raise ValueError(f"default_scope must be one of: {supported}")
        return normalized

    @field_validator("trace_query_capture", "trace_result_content_capture")
    @classmethod
    def normalize_trace_capture_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_TRACE_CAPTURE_MODES:
            supported = ", ".join(sorted(_ALLOWED_TRACE_CAPTURE_MODES))
            raise ValueError(f"trace capture mode must be one of: {supported}")
        return normalized

    @model_validator(mode="after")
    def validate_context_bounds(self) -> "MemoryDefaultsConfig":
        if self.max_result_chars > self.max_total_context_chars:
            raise ValueError(
                "max_result_chars must be less than or equal to max_total_context_chars"
            )
        return self


class MemoryStoreDatabaseConfig(StrictConfigModel):
    path: str = "memory"
    create_if_missing: bool = True
    schema_version: int = Field(default=1, ge=1)
    embedded_single_process: bool = True

    @field_validator("path")
    @classmethod
    def normalize_database_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("path must not be empty")
        return normalized


class MemoryEmbeddingsConfig(StrictConfigModel):
    provider: str = "fastembed"
    model: str = "BAAI/bge-small-en-v1.5"
    model_version: str | None = None
    dimension: int | None = Field(default=384, ge=1)
    batch_size: int = Field(default=64, ge=1)
    normalize: bool = True
    dimension_mismatch: str = "error"

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_dimension(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        data = dict(value)
        if "dimension" not in data and "dim" in data:
            data["dimension"] = data.pop("dim")
        return data

    @field_validator("provider", "model")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("model_version")
    @classmethod
    def normalize_optional_model_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("dimension_mismatch")
    @classmethod
    def normalize_dimension_mismatch(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_MEMORY_DIMENSION_MISMATCH_POLICIES:
            supported = ", ".join(sorted(_ALLOWED_MEMORY_DIMENSION_MISMATCH_POLICIES))
            raise ValueError(f"dimension_mismatch must be one of: {supported}")
        return normalized


class MemoryRerankerConfig(StrictConfigModel):
    enabled: bool = True
    provider: str = "fastembed"
    model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    model_version: str | None = None
    top_n: int = Field(default=60, ge=1)

    @field_validator("provider", "model")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("model_version")
    @classmethod
    def normalize_optional_model_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class MemoryStoreConfig(StrictConfigModel):
    config_path: str | None = None
    database: MemoryStoreDatabaseConfig = Field(default_factory=MemoryStoreDatabaseConfig)
    embeddings: MemoryEmbeddingsConfig = Field(default_factory=MemoryEmbeddingsConfig)
    reranker: MemoryRerankerConfig = Field(default_factory=MemoryRerankerConfig)

    @field_validator("config_path")
    @classmethod
    def normalize_optional_config_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class MemoryChunkingConfig(StrictConfigModel):
    strategy: str = "markdown_section"
    max_tokens: int = Field(default=350, ge=1)
    overlap_tokens: int = Field(default=50, ge=0)
    include_heading_path: bool = True
    include_frontmatter_in_embedding: bool = True
    preserve_code_blocks: bool = True
    removed_chunk_policy: str = "mark_removed"

    @field_validator("strategy")
    @classmethod
    def normalize_strategy(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("strategy must not be empty")
        return normalized

    @field_validator("removed_chunk_policy")
    @classmethod
    def normalize_removed_chunk_policy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_MEMORY_REMOVED_CHUNK_POLICIES:
            supported = ", ".join(sorted(_ALLOWED_MEMORY_REMOVED_CHUNK_POLICIES))
            raise ValueError(f"removed_chunk_policy must be one of: {supported}")
        return normalized

    @model_validator(mode="after")
    def validate_overlap(self) -> "MemoryChunkingConfig":
        if self.overlap_tokens >= self.max_tokens:
            raise ValueError("overlap_tokens must be less than max_tokens")
        return self


class MemorySearchConfig(StrictConfigModel):
    limit_max: int = Field(default=30, ge=1, le=100)
    vector_top_n: int = Field(default=30, ge=1)
    fts_top_n: int = Field(default=30, ge=1)
    rrf_k: int = Field(default=60, ge=1)
    graph_expansion_enabled: bool = True
    graph_expansion_hops: int = Field(default=1, ge=0, le=1)
    final_top_k: int = Field(default=10, ge=1)
    include_component_scores: bool = True
    include_debug: bool = False

    @model_validator(mode="after")
    def validate_top_k_order(self) -> "MemorySearchConfig":
        if self.final_top_k > self.limit_max:
            raise ValueError("final_top_k must be less than or equal to limit_max")
        return self


class MemoryScoringWeightsConfig(StrictConfigModel):
    reranker: float = Field(default=0.45, ge=0.0, le=1.0)
    retrieval_fusion: float = Field(default=0.15, ge=0.0, le=1.0)
    vector: float = Field(default=0.10, ge=0.0, le=1.0)
    full_text: float = Field(default=0.08, ge=0.0, le=1.0)
    temporal: float = Field(default=0.07, ge=0.0, le=1.0)
    importance: float = Field(default=0.06, ge=0.0, le=1.0)
    confidence: float = Field(default=0.04, ge=0.0, le=1.0)
    graph: float = Field(default=0.03, ge=0.0, le=1.0)
    user_rating: float = Field(default=0.02, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_total_weight(self) -> "MemoryScoringWeightsConfig":
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("At least one scoring weight must be greater than zero.")
        return self


class MemoryScoringConfig(StrictConfigModel):
    weights: MemoryScoringWeightsConfig = Field(default_factory=MemoryScoringWeightsConfig)


class MemoryLifecycleConfig(StrictConfigModel):
    allow_writes: bool = False
    default_ttl_days: int | None = Field(default=None, ge=1)
    contradiction_policy: str = "keep_both_mark_conflict"
    supersede_policy: str = "mark_previous_superseded"
    require_durable_scope_for_writes: bool = True
    allow_session_scope_only_writes: bool = False
    require_durable_scope_for_delete_export: bool = True

    @field_validator("contradiction_policy", "supersede_policy")
    @classmethod
    def normalize_policy_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized


class MemoryPrivacyConfig(StrictConfigModel):
    default_sensitivity: str = "internal"
    allow_llm_context_default: bool = True
    allow_retrieval_default: bool = True
    delete_by_scope_requires_confirm: bool = True
    enable_export_by_scope: bool = False
    enable_delete_by_scope: bool = False
    hard_delete_enabled: bool = False
    tombstone_on_forget: bool = True
    require_policy_approval_for_delete_export: bool = True

    @field_validator("default_sensitivity")
    @classmethod
    def normalize_default_sensitivity(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_MEMORY_SENSITIVITY_LEVELS:
            supported = ", ".join(sorted(_ALLOWED_MEMORY_SENSITIVITY_LEVELS))
            raise ValueError(f"default_sensitivity must be one of: {supported}")
        return normalized


class MemoryHealthConfig(StrictConfigModel):
    deep_check_enabled: bool = False


class MemoryConfig(StrictConfigModel):
    enabled: bool = False
    provider: str = "memory_store"
    required: bool = False
    defaults: MemoryDefaultsConfig = Field(default_factory=MemoryDefaultsConfig)
    store: MemoryStoreConfig = Field(default_factory=MemoryStoreConfig)
    chunking: MemoryChunkingConfig = Field(default_factory=MemoryChunkingConfig)
    search: MemorySearchConfig = Field(default_factory=MemorySearchConfig)
    scoring: MemoryScoringConfig = Field(default_factory=MemoryScoringConfig)
    lifecycle: MemoryLifecycleConfig = Field(default_factory=MemoryLifecycleConfig)
    privacy: MemoryPrivacyConfig = Field(default_factory=MemoryPrivacyConfig)
    health: MemoryHealthConfig = Field(default_factory=MemoryHealthConfig)

    @field_validator("provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_MEMORY_PROVIDER_TYPES:
            supported = ", ".join(sorted(_ALLOWED_MEMORY_PROVIDER_TYPES))
            raise ValueError(f"provider must be one of: {supported}")
        return normalized

    @model_validator(mode="after")
    def validate_provider_requirements(self) -> "MemoryConfig":
        if self.enabled and self.provider in {"disabled", "none"}:
            raise ValueError("enabled memory requires a concrete provider")
        if self.provider == "memory_store" and self.store.embeddings.dimension is None:
            raise ValueError("memory_store embeddings.dimension must not be null")
        if self.required and self.provider in {"disabled", "none"}:
            raise ValueError("required memory cannot use a disabled provider")
        if self.required and not self.enabled:
            raise ValueError("required memory cannot be disabled")
        if self.defaults.top_k > self.search.limit_max:
            raise ValueError("defaults.top_k must be less than or equal to search.limit_max")
        return self


class PolicyNamedAccessConfig(StrictConfigModel):
    allowed: list[str] = Field(default_factory=list)

    @field_validator("allowed")
    @classmethod
    def normalize_allowed(cls, value: list[str]) -> list[str]:
        return _normalize_name_list(value, field_name="allowed")


class PolicyLLMPolicyConfig(StrictConfigModel):
    deny_unknown_profiles: bool = True
    allowed_profiles: list[str] = Field(default_factory=list)
    allow_prompt_trace: bool = False
    allow_completion_trace: bool = False

    @field_validator("allowed_profiles")
    @classmethod
    def normalize_allowed_profiles(cls, value: list[str]) -> list[str]:
        return _normalize_name_list(value, field_name="allowed_profiles")


class PolicyMemoryPolicyConfig(StrictConfigModel):
    require_scope: bool = True
    allow_writes: bool = False
    allowed_read_scopes: list[str] = Field(default_factory=list)
    allowed_write_scopes: list[str] = Field(default_factory=list)

    @field_validator("allowed_read_scopes", "allowed_write_scopes")
    @classmethod
    def normalize_memory_scopes(cls, value: list[str], info: Any) -> list[str]:
        normalized = _normalize_name_list(value, field_name=str(info.field_name))
        invalid = sorted(set(normalized) - set(_ALLOWED_AGENT_MEMORY_SCOPES))
        if invalid:
            supported = ", ".join(sorted(_ALLOWED_AGENT_MEMORY_SCOPES))
            raise ValueError(
                f"{info.field_name} must only contain supported values: {supported}"
            )
        return normalized


class PolicyToolPolicyConfig(StrictConfigModel):
    deny_unknown_tools: bool = True
    allowed_tools: list[str] = Field(default_factory=list)
    allow_write_tools: bool = False
    allow_destructive_tools: bool = False
    allow_external_side_effect_tools: bool = False
    allow_approval_required_tools: bool = False

    @field_validator("allowed_tools")
    @classmethod
    def normalize_allowed_tools(cls, value: list[str]) -> list[str]:
        return _normalize_name_list(value, field_name="allowed_tools")


class PolicyApprovalConfig(StrictConfigModel):
    require_approval_for_write_tools: bool = True
    require_approval_for_destructive_tools: bool = True
    require_approval_for_external_side_effect_tools: bool = True
    require_approval_for_memory_writes: bool = False


class PolicyFallbackConfig(StrictConfigModel):
    allow_fallbacks: bool = True
    allow_after_denial: bool = False
    allow_after_external_side_effects: bool = False
    allowed_strategies: list[str] = Field(default_factory=list)

    @field_validator("allowed_strategies")
    @classmethod
    def normalize_allowed_strategies(cls, value: list[str]) -> list[str]:
        return _normalize_name_list(value, field_name="allowed_strategies")


class PolicyTraceConfig(StrictConfigModel):
    allow_trace: bool = True
    expose_raw_payloads: bool = False
    expose_prompt_text: bool = False
    expose_completion_text: bool = False


class PolicyStreamConfig(StrictConfigModel):
    allow_stream_events: bool = True
    expose_internal_events: bool = False
    expose_raw_deltas: bool = False


class PolicyCapabilityConfig(StrictConfigModel):
    expose_enabled: bool = True
    include_policy_profiles: bool = False
    include_denied_actions: bool = False


class PolicyHealthPolicyConfig(StrictConfigModel):
    expose_enabled: bool = True
    include_profile_names: bool = True
    include_decision_counts: bool = False


class PolicyAuditConfig(StrictConfigModel):
    enabled: bool = True
    include_reason_codes: bool = True
    include_actor_identifiers: bool = False
    include_resource_names: bool = True


class PolicyDecisionCacheConfig(StrictConfigModel):
    enabled: bool = True
    ttl_seconds: int = Field(default=30, ge=0, le=3600)
    max_entries: int = Field(default=1024, ge=1, le=100000)


class PolicyProfileConfig(StrictConfigModel):
    enabled: bool = True
    mode: str | None = None
    default_decision: str | None = None
    fail_closed: bool | None = None
    deny_unknown_tools: bool = True
    deny_unknown_llm_profiles: bool = True
    require_memory_scope: bool = True
    allow_memory_writes: bool = False
    allow_write_tools: bool = False
    allow_destructive_tools: bool = False
    allow_external_side_effect_tools: bool = False
    allow_approval_required_tools: bool = False
    usecases: PolicyNamedAccessConfig = Field(default_factory=PolicyNamedAccessConfig)
    strategies: PolicyNamedAccessConfig = Field(default_factory=PolicyNamedAccessConfig)
    agents: PolicyNamedAccessConfig = Field(default_factory=PolicyNamedAccessConfig)
    llm: PolicyLLMPolicyConfig = Field(default_factory=PolicyLLMPolicyConfig)
    memory: PolicyMemoryPolicyConfig = Field(default_factory=PolicyMemoryPolicyConfig)
    tools: PolicyToolPolicyConfig = Field(default_factory=PolicyToolPolicyConfig)
    approval: PolicyApprovalConfig = Field(default_factory=PolicyApprovalConfig)
    fallback: PolicyFallbackConfig = Field(default_factory=PolicyFallbackConfig)
    trace: PolicyTraceConfig = Field(default_factory=PolicyTraceConfig)
    stream: PolicyStreamConfig = Field(default_factory=PolicyStreamConfig)
    capabilities: PolicyCapabilityConfig = Field(default_factory=PolicyCapabilityConfig)
    health: PolicyHealthPolicyConfig = Field(default_factory=PolicyHealthPolicyConfig)
    audit: PolicyAuditConfig = Field(default_factory=PolicyAuditConfig)
    decision_cache: PolicyDecisionCacheConfig = Field(
        default_factory=PolicyDecisionCacheConfig
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_compatibility_fields(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        data = dict(value)

        def _section(name: str) -> dict[str, Any]:
            raw = data.get(name)
            return dict(raw) if isinstance(raw, Mapping) else {}

        llm = _section("llm")
        llm.setdefault(
            "deny_unknown_profiles",
            data.get("deny_unknown_llm_profiles", True),
        )
        data["llm"] = llm

        memory = _section("memory")
        memory.setdefault("require_scope", data.get("require_memory_scope", True))
        memory.setdefault("allow_writes", data.get("allow_memory_writes", False))
        data["memory"] = memory

        tools = _section("tools")
        tools.setdefault("deny_unknown_tools", data.get("deny_unknown_tools", True))
        tools.setdefault("allow_write_tools", data.get("allow_write_tools", False))
        tools.setdefault(
            "allow_destructive_tools",
            data.get("allow_destructive_tools", False),
        )
        tools.setdefault(
            "allow_external_side_effect_tools",
            data.get("allow_external_side_effect_tools", False),
        )
        tools.setdefault(
            "allow_approval_required_tools",
            data.get("allow_approval_required_tools", False),
        )
        data["tools"] = tools
        return data

    @field_validator("mode")
    @classmethod
    def normalize_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_POLICY_MODES:
            supported = ", ".join(sorted(_ALLOWED_POLICY_MODES))
            raise ValueError(f"mode must be one of: {supported}")
        return normalized

    @field_validator("default_decision")
    @classmethod
    def normalize_default_decision(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_POLICY_DEFAULT_DECISIONS:
            supported = ", ".join(sorted(_ALLOWED_POLICY_DEFAULT_DECISIONS))
            raise ValueError(f"default_decision must be one of: {supported}")
        return normalized


class PolicyConfig(StrictConfigModel):
    enabled: bool = True
    mode: str = "enforce"
    default_decision: str = "deny"
    fail_closed: bool = True
    default_profile: str = "default"
    profiles: dict[str, PolicyProfileConfig] = Field(default_factory=dict)

    @field_validator("mode")
    @classmethod
    def normalize_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_POLICY_MODES:
            supported = ", ".join(sorted(_ALLOWED_POLICY_MODES))
            raise ValueError(f"mode must be one of: {supported}")
        return normalized

    @field_validator("default_decision")
    @classmethod
    def normalize_default_decision(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_POLICY_DEFAULT_DECISIONS:
            supported = ", ".join(sorted(_ALLOWED_POLICY_DEFAULT_DECISIONS))
            raise ValueError(f"default_decision must be one of: {supported}")
        return normalized

    @model_validator(mode="after")
    def validate_profiles(self) -> "PolicyConfig":
        if self.default_profile not in self.profiles:
            raise ValueError(
                f"default_profile '{self.default_profile}' must reference a configured policy profile"
            )
        return self


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


class DeploymentMetricsConfig(StrictConfigModel):
    enabled: bool = True
    bind_host: str = "127.0.0.1"
    port: int = Field(default=9102, ge=1, le=65535)

    @field_validator("bind_host")
    @classmethod
    def normalize_bind_host(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("bind_host must not be empty")
        return normalized


class DeploymentReadinessConfig(StrictConfigModel):
    enabled: bool = True
    bind_host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)

    @field_validator("bind_host")
    @classmethod
    def normalize_optional_bind_host(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class DeploymentConfig(StrictConfigModel):
    profile: str = "local"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    public_base_url: str | None = None
    log_dir: str = "logs"
    runtime_dir: str = "runtime"
    graceful_shutdown_seconds: int = Field(default=20, ge=1, le=3600)
    metrics: DeploymentMetricsConfig = Field(default_factory=DeploymentMetricsConfig)
    readiness: DeploymentReadinessConfig = Field(default_factory=DeploymentReadinessConfig)

    @field_validator("profile")
    @classmethod
    def normalize_profile(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_DEPLOYMENT_PROFILES:
            supported = ", ".join(sorted(_ALLOWED_DEPLOYMENT_PROFILES))
            raise ValueError(f"profile must be one of: {supported}")
        return normalized

    @field_validator("host", "log_dir", "runtime_dir")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("public_base_url")
    @classmethod
    def normalize_public_base_url(cls, value: str | None) -> str | None:
        return _normalize_optional_url_value(value, allowed_schemes=_ALLOWED_CORS_ORIGIN_SCHEMES)

    @model_validator(mode="after")
    def validate_profile_safety(self) -> "DeploymentConfig":
        if self.profile in {"staging", "production"}:
            for relative_path in (self.log_dir, self.runtime_dir):
                normalized = relative_path.replace("\\", "/").strip()
                if normalized in {"logs", "runtime"}:
                    raise ValueError(
                        "staging and production profiles require deployment directories outside backend source defaults"
                    )
        return self


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
    restart_enabled: bool = False
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


class SessionIdentifiersConfig(StrictConfigModel):
    prefix: str = "session"
    accept_client_session_id: bool = True
    generate_when_missing: bool = True
    max_length: int = Field(default=128, ge=3, le=128)
    allowed_pattern: str = r"^[A-Za-z0-9_.:-]{3,128}$"

    @field_validator("prefix")
    @classmethod
    def normalize_prefix(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("prefix must not be empty")
        if not _SESSION_ID_PREFIX_PATTERN.fullmatch(normalized):
            raise ValueError("prefix must contain only session identifier characters")
        return normalized

    @field_validator("allowed_pattern")
    @classmethod
    def validate_allowed_pattern(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("allowed_pattern must not be empty")
        try:
            re.compile(normalized)
        except re.error as exc:
            raise ValueError("allowed_pattern must be a valid regular expression") from exc
        return normalized


class SessionDefaultsConfig(StrictConfigModel):
    default_user_id: str = "local_user"
    default_usecase: str | None = None
    default_history_limit: int = Field(default=50, ge=1)
    max_history_limit: int = Field(default=200, ge=1)
    timezone_metadata_key: str = "timezone"

    @field_validator("default_user_id", "timezone_metadata_key")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("default_usecase")
    @classmethod
    def normalize_optional_usecase(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("default_usecase must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_history_limits(self) -> SessionDefaultsConfig:
        if self.default_history_limit > self.max_history_limit:
            raise ValueError(
                "default_history_limit must be less than or equal to max_history_limit"
            )
        return self


class SessionLifecycleConfig(StrictConfigModel):
    create_on_first_chat: bool = True
    resume_existing_sessions: bool = True
    reject_unknown_client_session_id: bool = False
    update_last_seen_on_load: bool = True
    save_after_failed_orchestration: bool = True
    save_after_cancelled_stream: bool = True


class SessionConcurrencyConfig(StrictConfigModel):
    mode: str = "optimistic_version"
    conflict_policy: str = "reject"
    max_retries: int = Field(default=1, ge=0, le=10)

    @field_validator("mode")
    @classmethod
    def normalize_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_SESSION_CONCURRENCY_MODES:
            supported = ", ".join(sorted(_ALLOWED_SESSION_CONCURRENCY_MODES))
            raise ValueError(f"mode must be one of: {supported}")
        return normalized

    @field_validator("conflict_policy")
    @classmethod
    def normalize_conflict_policy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_SESSION_CONFLICT_POLICIES:
            supported = ", ".join(sorted(_ALLOWED_SESSION_CONFLICT_POLICIES))
            raise ValueError(f"conflict_policy must be one of: {supported}")
        return normalized


class SessionStateConfig(StrictConfigModel):
    save_on_chat_completion: bool = True
    save_on_stream_completion: bool = True
    save_on_stream_cancellation: bool = True
    save_on_stream_failure: bool = True
    save_each_stream_delta: bool = False

    @model_validator(mode="after")
    def validate_stream_save_flags(self) -> SessionStateConfig:
        if self.save_each_stream_delta and not self.save_on_stream_completion:
            raise ValueError(
                "save_each_stream_delta requires save_on_stream_completion to be true"
            )
        return self


class SessionHistoryConfig(StrictConfigModel):
    enabled: bool = False
    include_tool_summaries: bool = False
    include_system_messages: bool = False
    include_metadata: bool = True
    max_message_chars: int = Field(default=4000, ge=1, le=20000)
    redaction_enabled: bool = True


class SessionManagementConfig(StrictConfigModel):
    list_enabled: bool = False
    delete_enabled: bool = False
    default_list_limit: int = Field(default=50, ge=1, le=500)
    max_list_limit: int = Field(default=200, ge=1, le=500)


class SessionTracingConfig(StrictConfigModel):
    record_session_created: bool = True
    record_session_resumed: bool = True
    record_session_reset: bool = True
    record_state_loaded: bool = True
    record_state_saved: bool = True
    record_history_returned: bool = True
    record_stream_lifecycle: bool = True


class SessionConfig(StrictConfigModel):
    enabled: bool = True
    identifiers: SessionIdentifiersConfig = Field(default_factory=SessionIdentifiersConfig)
    defaults: SessionDefaultsConfig = Field(default_factory=SessionDefaultsConfig)
    lifecycle: SessionLifecycleConfig = Field(default_factory=SessionLifecycleConfig)
    concurrency: SessionConcurrencyConfig = Field(default_factory=SessionConcurrencyConfig)
    state: SessionStateConfig = Field(default_factory=SessionStateConfig)
    history: SessionHistoryConfig = Field(default_factory=SessionHistoryConfig)
    management: SessionManagementConfig = Field(default_factory=SessionManagementConfig)
    tracing: SessionTracingConfig = Field(default_factory=SessionTracingConfig)


class BackendConfig(StrictConfigModel):
    @model_validator(mode="before")
    @classmethod
    def normalize_compatibility_sources(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        data = dict(value)
        raw_app = data.get("app")
        app = dict(raw_app) if isinstance(raw_app, Mapping) else {}
        raw_memory = data.get("memory")
        memory = dict(raw_memory) if isinstance(raw_memory, Mapping) else {}
        raw_tooling = data.get("tooling")
        tooling = dict(raw_tooling) if isinstance(raw_tooling, Mapping) else {}
        raw_features = data.get("features")
        features = dict(raw_features) if isinstance(raw_features, Mapping) else {}
        raw_orchestration = data.get("orchestration")
        orchestration = (
            dict(raw_orchestration)
            if isinstance(raw_orchestration, Mapping)
            else {}
        )
        raw_orchestration_defaults = orchestration.get("defaults")
        orchestration_defaults = (
            dict(raw_orchestration_defaults)
            if isinstance(raw_orchestration_defaults, Mapping)
            else {}
        )
        orchestration_strategies = _mapping_to_dict_of_mappings(
            orchestration.get("strategies")
        )
        orchestration_usecases = _mapping_to_dict_of_mappings(
            orchestration.get("usecases")
        )
        raw_persistence = data.get("persistence")
        persistence = dict(raw_persistence) if isinstance(raw_persistence, Mapping) else {}
        raw_persistence_memory = persistence.get("memory")
        persistence_memory = (
            dict(raw_persistence_memory)
            if isinstance(raw_persistence_memory, Mapping)
            else {}
        )
        legacy_usecases = _mapping_to_dict_of_mappings(data.get("usecases"))
        legacy_strategies = _mapping_to_dict_of_mappings(data.get("strategies"))

        if "enabled" not in memory and "memory_enabled" in features:
            memory["enabled"] = features["memory_enabled"]

        if "enabled" not in tooling and "tools_enabled" in features:
            tooling["enabled"] = features["tools_enabled"]

        if "provider" not in memory:
            legacy_provider = persistence_memory.get("provider")
            if isinstance(legacy_provider, str) and legacy_provider.strip():
                memory["provider"] = legacy_provider

        if "required" not in memory and "required" in persistence_memory:
            memory["required"] = persistence_memory["required"]

        if "enabled" in memory:
            features["memory_enabled"] = memory["enabled"]
            data["features"] = features

        if "enabled" in tooling:
            features["tools_enabled"] = tooling["enabled"]
            data["features"] = features

        if "provider" in memory:
            persistence_memory["provider"] = memory["provider"]
        if "required" in memory:
            persistence_memory["required"] = memory["required"]
        if persistence_memory:
            persistence["memory"] = persistence_memory
            data["persistence"] = persistence

        if memory:
            data["memory"] = memory

        if tooling:
            data["tooling"] = tooling

        for strategy_name, legacy_strategy in legacy_strategies.items():
            orchestration_strategies[strategy_name] = _merge_nested_mappings(
                orchestration_strategies.get(strategy_name, {}),
                _translate_legacy_strategy_to_orchestration(legacy_strategy),
            )

        for usecase_name, legacy_usecase in legacy_usecases.items():
            orchestration_usecases[usecase_name] = _merge_nested_mappings(
                orchestration_usecases.get(usecase_name, {}),
                _translate_legacy_usecase_to_orchestration(legacy_usecase),
            )

        default_usecase_name = _normalize_optional_text(
            app.get("active_usecase") if isinstance(app.get("active_usecase"), str) else None
        )
        default_strategy_name = orchestration_defaults.get("strategy")
        if not _has_non_blank_value(default_strategy_name) and default_usecase_name is not None:
            usecase_section = orchestration_usecases.get(default_usecase_name, {})
            candidate_strategy = usecase_section.get("strategy")
            if isinstance(candidate_strategy, str) and candidate_strategy.strip() != "":
                orchestration_defaults["strategy"] = candidate_strategy.strip()

        fallback_strategy_name = orchestration_defaults.get("fallback_strategy")
        if not _has_non_blank_value(fallback_strategy_name) and _has_non_blank_value(
            orchestration_defaults.get("strategy")
        ):
            orchestration_defaults["fallback_strategy"] = orchestration_defaults["strategy"]

        if orchestration_defaults:
            orchestration["defaults"] = orchestration_defaults
        if orchestration_strategies:
            orchestration["strategies"] = orchestration_strategies
        if orchestration_usecases:
            orchestration["usecases"] = orchestration_usecases
        if orchestration:
            orchestration.setdefault("enabled", True)
            data["orchestration"] = orchestration

        if orchestration_strategies:
            data["strategies"] = {
                strategy_name: _translate_orchestration_strategy_to_legacy(
                    strategy_section
                )
                for strategy_name, strategy_section in orchestration_strategies.items()
            }

        if orchestration_usecases:
            data["usecases"] = {
                usecase_name: _translate_orchestration_usecase_to_legacy(
                    usecase_section,
                    strategy_section=orchestration_strategies.get(
                        _read_mapping_value_as_str(usecase_section, "strategy") or ""
                    ),
                )
                for usecase_name, usecase_section in orchestration_usecases.items()
            }

        return data

    app: AppConfig
    api: ApiConfig = Field(default_factory=ApiConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    features: FeatureConfig = Field(default_factory=FeatureConfig)
    orchestration: OrchestrationConfig = Field(default_factory=OrchestrationConfig)
    usecases: dict[str, UseCaseConfig]
    strategies: dict[str, StrategyConfig]
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    llm: LLMConfig
    tooling: ToolingConfig = Field(default_factory=ToolingConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    mcp: MCPConfig
    persistence: PersistenceConfig
    deployment: DeploymentConfig = Field(default_factory=DeploymentConfig)
    policy: PolicyConfig
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)


def _has_non_blank_value(value: str | None) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _mapping_to_dict_of_mappings(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for raw_key, raw_item in value.items():
        if isinstance(raw_key, str) and isinstance(raw_item, Mapping):
            result[raw_key] = dict(raw_item)
    return result


def _merge_nested_mappings(
    base: Mapping[str, Any],
    override: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = _merge_nested_mappings(current, value)
            continue
        merged[key] = value
    return merged


def _translate_legacy_strategy_to_orchestration(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    translated = dict(value)
    if "type" in translated and isinstance(translated["type"], str):
        translated["type"] = _normalize_orchestration_strategy_type(translated["type"])
    return translated


def _translate_legacy_usecase_to_orchestration(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    translated = dict(value)
    default_agent = translated.pop("default_agent", None)
    if default_agent is not None and "agent" not in translated:
        translated["agent"] = default_agent

    orchestrator_llm_profile = translated.pop("orchestrator_llm_profile", None)
    if orchestrator_llm_profile is not None and "llm_profile" not in translated:
        translated["llm_profile"] = orchestrator_llm_profile
    return translated


def _translate_orchestration_strategy_to_legacy(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    translated = {
        "enabled": value.get("enabled", True),
        "type": value.get("type", "direct_agent"),
    }

    for field_name in (
        "description",
        "llm_profile",
        "max_candidate_agents",
        "metadata",
    ):
        field_value = value.get(field_name)
        if field_value is not None:
            translated[field_name] = field_value

    return translated


def _translate_orchestration_usecase_to_legacy(
    value: Mapping[str, Any],
    *,
    strategy_section: Mapping[str, Any] | None,
) -> dict[str, Any]:
    strategy_default_agent = _read_mapping_value_as_str(strategy_section, "default_agent")
    agent_name = _read_mapping_value_as_str(value, "agent") or strategy_default_agent

    allowed_agents_value = value.get("allowed_agents")
    allowed_agents: list[str]
    if isinstance(allowed_agents_value, list):
        allowed_agents = [item for item in allowed_agents_value if isinstance(item, str)]
    elif agent_name is not None:
        allowed_agents = [agent_name]
    else:
        allowed_agents = []

    translated = {
        "enabled": value.get("enabled", True),
        "strategy": value.get("strategy"),
        "default_agent": agent_name,
        "allowed_agents": allowed_agents,
        "policy_profile": value.get("policy_profile", "default"),
    }

    for field_name in ("description", "memory", "tools", "metadata"):
        field_value = value.get(field_name)
        if field_value is not None:
            translated[field_name] = field_value

    llm_profile = _read_mapping_value_as_str(value, "llm_profile")
    if llm_profile is not None:
        translated["orchestrator_llm_profile"] = llm_profile

    display_name = _read_mapping_value_as_str(value, "display_name")
    if display_name is not None:
        translated.setdefault("metadata", {})
        metadata = translated["metadata"]
        if isinstance(metadata, Mapping):
            metadata_dict = dict(metadata)
            metadata_dict.setdefault("display_name", display_name)
            translated["metadata"] = metadata_dict

    return translated


def _translate_legacy_agent_to_plugin(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    translated = dict(value)

    if not _has_non_blank_value(_read_mapping_value_as_str(value, "type")):
        translated["type"] = "custom"

    if not isinstance(translated.get("capabilities"), Mapping):
        translated["capabilities"] = _translate_legacy_agent_capabilities(value)

    if "allowed_tool_intents" not in translated and isinstance(
        value.get("allowed_tools"),
        list,
    ):
        translated["allowed_tool_intents"] = list(value.get("allowed_tools", []))

    return translated


def _translate_legacy_agent_capabilities(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    raw_memory = value.get("memory")
    memory = dict(raw_memory) if isinstance(raw_memory, Mapping) else {}
    allowed_tools = value.get("allowed_tools")
    tool_enabled = isinstance(allowed_tools, list) and any(
        isinstance(item, str) and item.strip() != "" for item in allowed_tools
    )
    legacy_capabilities = value.get("capabilities")
    review_enabled = isinstance(legacy_capabilities, list) and any(
        isinstance(item, str) and item.strip().lower() == "review"
        for item in legacy_capabilities
    )

    return {
        "answer": True,
        "review": review_enabled,
        "stream": True,
        "memory_read": bool(memory.get("search_enabled", False)),
        "memory_write": bool(memory.get("write_enabled", False)),
        "memory_candidate_extract": False,
        "tool_intents": tool_enabled,
        "tool_execute": False,
        "self_managed_memory": False,
        "self_managed_tools": False,
    }


def _apply_agent_defaults(
    defaults: Mapping[str, Any],
    plugin: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(plugin)

    if "enabled" not in merged and "enabled" in defaults:
        merged["enabled"] = defaults["enabled"]
    if "stream_llm_deltas" not in merged and "stream_llm_deltas" in defaults:
        merged["stream_llm_deltas"] = defaults["stream_llm_deltas"]
    if "expose_metadata" not in merged and "expose_agent_metadata" in defaults:
        merged["expose_metadata"] = defaults["expose_agent_metadata"]

    raw_limits = merged.get("limits")
    limits = dict(raw_limits) if isinstance(raw_limits, Mapping) else {}
    for key in (
        "max_prompt_context_bytes",
        "max_output_chars",
        "max_tool_intents",
        "max_memory_candidates",
        "max_llm_calls",
        "max_self_managed_tool_calls",
        "max_self_managed_memory_searches",
    ):
        if key not in limits and key in defaults:
            limits[key] = defaults[key]
    if limits or "limits" in merged:
        merged["limits"] = limits

    raw_context_policy = merged.get("context_policy")
    context_policy = (
        dict(raw_context_policy) if isinstance(raw_context_policy, Mapping) else {}
    )
    if "max_context_bytes" not in context_policy and "max_prompt_context_bytes" in defaults:
        context_policy["max_context_bytes"] = defaults["max_prompt_context_bytes"]
    if context_policy or "context_policy" in merged:
        merged["context_policy"] = context_policy

    raw_capabilities = merged.get("capabilities")
    capabilities = (
        dict(raw_capabilities)
        if isinstance(raw_capabilities, Mapping)
        else _translate_legacy_agent_capabilities(merged)
    )
    merged["capabilities"] = capabilities

    if "allowed_tools" not in merged and "allowed_tool_intents" in merged:
        raw_allowed_tool_intents = merged.get("allowed_tool_intents")
        merged["allowed_tools"] = (
            list(raw_allowed_tool_intents)
            if isinstance(raw_allowed_tool_intents, list)
            else []
        )

    raw_memory = merged.get("memory")
    memory = dict(raw_memory) if isinstance(raw_memory, Mapping) else {}
    if "search_enabled" not in memory:
        memory["search_enabled"] = bool(capabilities.get("memory_read", False))
    if "write_enabled" not in memory:
        memory["write_enabled"] = bool(capabilities.get("memory_write", False))
    merged["memory"] = memory

    if not _has_non_blank_value(_read_mapping_value_as_str(merged, "type")):
        if _read_mapping_value_as_str(merged, "module") or _read_mapping_value_as_str(
            merged,
            "class_name",
        ):
            merged["type"] = "custom"
        else:
            merged["type"] = "general_assistant"

    return merged


def _read_mapping_value_as_str(
    value: Mapping[str, Any] | None,
    key: str,
) -> str | None:
    if not isinstance(value, Mapping):
        return None

    candidate = value.get(key)
    if isinstance(candidate, str):
        normalized = candidate.strip()
        if normalized != "":
            return normalized
    return None


def _normalize_orchestration_strategy_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "direct":
        normalized = "direct_agent"
    if normalized not in _ALLOWED_ORCHESTRATION_STRATEGY_TYPES:
        supported = ", ".join(sorted(_ALLOWED_ORCHESTRATION_STRATEGY_TYPES))
        raise ValueError(f"type must be one of: {supported}")
    return normalized


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


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    if normalized == "":
        return None
    return normalized


def _normalize_optional_url_value(
    value: str | None,
    *,
    allowed_schemes: frozenset[str],
) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None

    parsed = urlsplit(normalized)
    if parsed.scheme not in allowed_schemes or parsed.netloc == "":
        supported = ", ".join(sorted(allowed_schemes))
        raise ValueError(f"must be a valid URL with scheme one of: {supported}")
    return normalized


def _normalize_name_list(value: list[str], *, field_name: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        stripped = item.strip()
        if stripped == "":
            raise ValueError(f"{field_name} entries must not be empty")
        if stripped not in seen:
            normalized.append(stripped)
            seen.add(stripped)
    return normalized


def _validate_mcp_auth_requirements(auth: MCPAuthConfig) -> None:
    if auth.mode == "none":
        return

    if auth.mode == "bearer" and not _has_non_blank_value(auth.token):
        raise ValueError("bearer auth requires token")

    if auth.mode == "jwt" and not _has_non_blank_value(auth.jwt):
        raise ValueError("jwt auth requires jwt")

    if auth.mode == "oauth_client_credentials":
        if not _has_non_blank_value(auth.oauth.token_url):
            raise ValueError("oauth_client_credentials auth requires oauth.token_url")
        if not _has_non_blank_value(auth.oauth.client_id):
            raise ValueError("oauth_client_credentials auth requires oauth.client_id")
        if not _has_non_blank_value(auth.oauth.client_secret):
            raise ValueError(
                "oauth_client_credentials auth requires oauth.client_secret"
            )


def _validate_json_schema_object(value: Mapping[str, Any]) -> None:
    _validate_json_schema_value(value, path="<root>")


def _validate_json_schema_value(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("schema override keys must be strings")

            if key == "type":
                _validate_json_schema_type(item)
            elif key == "properties" and not isinstance(item, Mapping):
                raise ValueError("schema override properties must be a mapping")
            elif key == "required":
                if not isinstance(item, list) or not all(isinstance(entry, str) for entry in item):
                    raise ValueError(
                        "schema override required must be a list of strings"
                    )
            elif key == "items" and not isinstance(item, (Mapping, list)):
                raise ValueError(
                    "schema override items must be a schema object or list"
                )

            _validate_json_schema_value(item, path=f"{path}.{key}")
        return

    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_schema_value(item, path=f"{path}[{index}]")
        return

    if value is None or isinstance(value, (bool, int, float, str)):
        return

    raise ValueError(f"schema override contains unsupported value at {path}")


def _validate_json_schema_type(value: Any) -> None:
    if isinstance(value, str):
        if value not in _ALLOWED_JSON_SCHEMA_TYPES:
            supported = ", ".join(sorted(_ALLOWED_JSON_SCHEMA_TYPES))
            raise ValueError(f"schema override type must be one of: {supported}")
        return

    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        invalid_types = [item for item in value if item not in _ALLOWED_JSON_SCHEMA_TYPES]
        if invalid_types:
            supported = ", ".join(sorted(_ALLOWED_JSON_SCHEMA_TYPES))
            raise ValueError(f"schema override type must be one of: {supported}")
        return

    raise ValueError("schema override type must be a string or list of strings")