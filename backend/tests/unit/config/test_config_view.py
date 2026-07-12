from collections.abc import Mapping
from pathlib import Path

import pytest

from app.config.loader import load_validated_config
from app.config.settings import BACKEND_ROOT
from app.config.redaction import REDACTED_VALUE
from app.config.view import (
    AgentCapabilitySettings,
    AgentContextPolicySettings,
    AgentLimitSettings,
    AgentMemorySettings,
    AgentPromptOverrideSettings,
    AgentPluginSettings,
    AgentsSettings,
    ApiDebugRoutesSettings,
    ApiRequestLimitSettings,
    ApiSessionSettings,
    ApiSettings,
    ApiSseSettings,
    ApiTracingSettings,
    CorsSettings,
    ConversationContextSettings,
    DeploymentMetricsSettings,
    DeploymentReadinessSettings,
    DeploymentSettings,
    HealthSettings,
    LLMDefaultsSettings,
    LLMProfileAllowlistSettings,
    LLMProfileSettings,
    LLMProviderSettings,
    LLMSettings,
    MCPAuthSettings,
    MCPServerSettings,
    MemoryChunkingSettings,
    MemoryDefaultsSettings,
    MemoryEmbeddingsSettings,
    MemoryHealthSettings,
    MemoryLifecycleSettings,
    MemoryPrivacySettings,
    MemoryRerankerSettings,
    MemoryScoringSettings,
    MemoryScoringWeightsSettings,
    MemorySearchSettings,
    MemorySettings,
    MemoryStoreDatabaseSettings,
    MemoryStoreSettings as MemoryStoreViewSettings,
    OrchestrationDefaultsSettings,
    OrchestrationSettings,
    ObservabilitySettings,
    PolicySettings,
    SessionConcurrencySettings,
    SessionDefaultsSettings,
    SessionHistorySettings,
    SessionIdentifierSettings,
    SessionLifecycleSettings,
    SessionManagementSettings,
    SessionSettings,
    SessionStateSettings,
    SessionTracingSettings,
    StrategySettings,
    ToolAllowedForSettings,
    ToolDefinitionSettings,
    ToolRegistrySettings,
    ToolingDefaultsSettings,
    ToolingSettings,
    UseCaseSettings,
    ValidatedConfigurationView,
    VisualizationArtifactStoreSqliteSettings,
    VisualizationArtifactStoreSettings,
    VisualizationContextSummarySettings,
    VisualizationHistoryReplaySettings,
    VisualizationLimitsSettings,
    VisualizationSampleDataSettings,
    VisualizationSettings,
    get_api_settings,
    get_agents_settings,
    get_deployment_settings,
    get_health_settings,
    get_llm_settings,
    get_memory_settings,
    get_observability_settings,
    get_policy_settings,
    get_orchestration_settings,
    get_session_settings,
    get_tooling_settings,
    get_visualization_settings,
)
from app.contracts.errors import ConfigurationError
from app.persistence.settings import (
    MemoryPersistenceSettings,
    MemoryStoreSettings,
    PersistenceSettings,
    SqliteTraceStoreSettings,
    SqliteWorkflowStateSettings,
    TracePersistenceSettings,
    WorkflowStatePersistenceSettings,
)
from app.persistence.paths import resolve_backend_path, resolve_data_path

TRACE_FIXTURE_PATH = "tests/fixtures/config/trace_sqlite.yaml"
CONFIG_FIXTURES_DIR = BACKEND_ROOT / "tests" / "fixtures" / "config"


def build_view() -> ValidatedConfigurationView:
    return ValidatedConfigurationView(
        {
            "app": {
                "environment": "local",
                "active_usecase": "support_chat",
            },
            "api": {
                "enabled": True,
                "base_path": "/api/v1",
                "docs_enabled": False,
                "openapi_enabled": False,
                "cors": {
                    "enabled": True,
                    "allow_origins": [
                        "http://localhost:5000",
                        "https://frontend.example.local",
                    ],
                    "allow_credentials": True,
                    "allow_methods": ["GET", "POST", "OPTIONS"],
                    "allow_headers": [
                        "Authorization",
                        "Content-Type",
                        "X-Request-Id",
                        "X-Trace-Id",
                    ],
                },
                "request_limits": {
                    "max_body_bytes": 8192,
                    "max_message_chars": 4096,
                    "max_metadata_bytes": 1024,
                    "request_timeout_seconds": 30,
                    "stream_timeout_seconds": 45,
                },
                "sessions": {
                    "accept_client_session_id": True,
                    "create_session_when_missing": False,
                    "session_id_header": "X-Session-Id",
                },
                "tracing": {
                    "accept_client_trace_id": True,
                    "response_trace_header": "X-Trace-Id",
                    "record_request_received": True,
                    "record_response_returned": False,
                    "record_validation_errors": True,
                },
                "debug_routes": {
                    "enabled": True,
                    "require_localhost": True,
                    "restart_enabled": True,
                    "max_trace_events": 25,
                    "max_search_results": 10,
                },
                "sse": {
                    "heartbeat_seconds": 5,
                    "send_trace_id_event": False,
                    "send_metadata_events": True,
                },
            },
            "session": {
                "enabled": True,
                "identifiers": {
                    "prefix": "session",
                    "accept_client_session_id": True,
                    "generate_when_missing": False,
                    "max_length": 96,
                    "allowed_pattern": "^[A-Za-z0-9_.:-]{3,96}$",
                },
                "defaults": {
                    "default_user_id": "local_user",
                    "default_usecase": "support_chat",
                    "default_history_limit": 25,
                    "max_history_limit": 100,
                    "timezone_metadata_key": "timezone",
                },
                "lifecycle": {
                    "create_on_first_chat": True,
                    "resume_existing_sessions": True,
                    "reject_unknown_client_session_id": False,
                    "update_last_seen_on_load": True,
                    "save_after_failed_orchestration": True,
                    "save_after_cancelled_stream": True,
                },
                "concurrency": {
                    "mode": "optimistic_version",
                    "conflict_policy": "reject",
                    "max_retries": 2,
                },
                "state": {
                    "save_on_chat_completion": True,
                    "save_on_stream_completion": True,
                    "save_on_stream_cancellation": True,
                    "save_on_stream_failure": True,
                    "save_each_stream_delta": False,
                },
                "history": {
                    "enabled": True,
                    "include_tool_summaries": False,
                    "include_system_messages": False,
                    "include_metadata": True,
                    "max_message_chars": 2048,
                    "redaction_enabled": True,
                },
                "management": {
                    "list_enabled": True,
                    "delete_enabled": False,
                    "default_list_limit": 25,
                    "max_list_limit": 100,
                },
                "tracing": {
                    "record_session_created": True,
                    "record_session_resumed": True,
                    "record_session_reset": True,
                    "record_state_loaded": True,
                    "record_state_saved": True,
                    "record_history_returned": False,
                    "record_stream_lifecycle": True,
                },
            },
            "llm": {
                "defaults": {
                    "profile": "cloud_fast",
                    "timeout_seconds": 60,
                    "stream_timeout_seconds": 90,
                    "max_retries": 2,
                    "trace_prompts": False,
                    "trace_completions": True,
                },
                "providers": {
                    "openai": {
                        "type": "openai",
                        "enabled": True,
                        "base_url": "https://api.openai.example/v1",
                        "api_key": "top-secret-key",
                        "timeout_seconds": 55,
                        "stream_timeout_seconds": 75,
                        "headers": {
                            "Authorization": "Bearer top-secret-key",
                        },
                        "extra": {"region": "test"},
                    }
                },
                "profiles": {
                    "cloud_fast": {
                        "enabled": True,
                        "provider": "openai",
                        "model": "gpt-4.1-mini",
                        "temperature": 0.2,
                        "top_p": 0.8,
                        "max_output_tokens": 1024,
                        "max_input_tokens": 4096,
                        "max_total_tokens": 8192,
                        "timeout_seconds": 45,
                        "stream_timeout_seconds": 70,
                        "supports_streaming": True,
                        "supports_json_schema": True,
                        "supports_tool_calling": False,
                        "allowed_for": {
                            "usecases": ["support_chat"],
                            "agents": ["support_agent"],
                            "strategies": ["direct_agent"],
                        },
                        "fallback_profiles": ["local_reasoning"],
                        "extra": {"tier": "fast"},
                    }
                },
            },
            "memory": {
                "enabled": False,
                "provider": "memory_store",
                "required": False,
                "defaults": {
                    "default_scope": "project",
                    "top_k": 5,
                    "include_agent_memories": True,
                    "include_document_chunks": True,
                    "include_graph_context": False,
                    "max_result_chars": 900,
                    "max_total_context_chars": 3600,
                    "trace_query_capture": "summaries_only",
                    "trace_result_content_capture": "none",
                },
                "store": {
                    "database": {
                        "path": "memory",
                        "create_if_missing": True,
                        "schema_version": 2,
                        "embedded_single_process": True,
                    },
                    "embeddings": {
                        "provider": "fastembed",
                        "model": "BAAI/bge-small-en-v1.5",
                        "dimension": 384,
                        "batch_size": 48,
                        "normalize": True,
                        "dimension_mismatch": "reembed",
                    },
                    "reranker": {
                        "enabled": False,
                        "provider": "fastembed",
                        "model": "Xenova/ms-marco-MiniLM-L-6-v2",
                        "top_n": 20,
                    },
                },
                "chunking": {
                    "strategy": "markdown_section",
                    "max_tokens": 320,
                    "overlap_tokens": 40,
                    "include_heading_path": True,
                    "include_frontmatter_in_embedding": False,
                    "preserve_code_blocks": True,
                    "removed_chunk_policy": "mark_removed",
                },
                "search": {
                    "limit_max": 15,
                    "vector_top_n": 25,
                    "fts_top_n": 20,
                    "rrf_k": 50,
                    "graph_expansion_enabled": True,
                    "graph_expansion_hops": 1,
                    "final_top_k": 10,
                    "include_component_scores": True,
                    "include_debug": False,
                },
                "scoring": {
                    "weights": {
                        "reranker": 0.4,
                        "retrieval_fusion": 0.15,
                        "vector": 0.12,
                        "full_text": 0.08,
                        "temporal": 0.08,
                        "importance": 0.06,
                        "confidence": 0.04,
                        "graph": 0.04,
                        "user_rating": 0.03,
                    },
                },
                "lifecycle": {
                    "allow_writes": False,
                    "default_ttl_days": None,
                    "contradiction_policy": "keep_both_mark_conflict",
                    "supersede_policy": "mark_previous_superseded",
                    "require_durable_scope_for_writes": True,
                    "allow_session_scope_only_writes": False,
                    "require_durable_scope_for_delete_export": True,
                },
                "privacy": {
                    "default_sensitivity": "internal",
                    "allow_llm_context_default": True,
                    "allow_retrieval_default": True,
                    "delete_by_scope_requires_confirm": True,
                    "enable_export_by_scope": False,
                    "enable_delete_by_scope": False,
                    "hard_delete_enabled": False,
                    "tombstone_on_forget": True,
                    "require_policy_approval_for_delete_export": True,
                },
                "health": {
                    "deep_check_enabled": False,
                },
            },
            "observability": {
                "log_level": "DEBUG",
                "structured_logging": True,
                "trace_enabled": True,
                "trace_payloads_enabled": False,
                "trace_store_required": True,
                "redact_secrets": True,
                "include_stack_traces_in_logs": False,
                "include_stack_traces_in_traces": False,
                "max_trace_payload_chars": 4096,
                "slow_request_ms": 2500,
                "slow_llm_call_ms": 15000,
                "slow_tool_call_ms": 5000,
                "metrics_enabled": True,
            },
            "health": {
                "expose_config_summary": True,
                "expose_provider_names": True,
                "expose_secret_values": False,
                "include_component_details": True,
            },
            "deployment": {
                "profile": "local",
                "host": "0.0.0.0",
                "port": 8010,
                "public_base_url": "http://localhost:8010",
                "log_dir": "var/log/backend",
                "runtime_dir": "var/run/backend",
                "graceful_shutdown_seconds": 25,
                "metrics": {
                    "enabled": True,
                    "bind_host": "127.0.0.1",
                    "port": 9200,
                },
                "readiness": {
                    "enabled": True,
                    "bind_host": "127.0.0.1",
                    "port": 9201,
                },
            },
            "persistence": {
                "base_dir": "./data",
                "workflow_state": {
                    "provider": "sqlite",
                    "sqlite": {
                        "path": "workflow_state.db",
                        "create_parent_dirs": True,
                        "initialize_schema": True,
                        "journal_mode": "WAL",
                        "synchronous": "full",
                        "busy_timeout_ms": 5000,
                        "foreign_keys": True,
                        "required": True,
                        "max_state_bytes": 4096,
                        "max_history_messages": 25,
                        "reset_mode": "delete_state_row",
                        "store_user_id": True,
                        "store_user_id_hash": False,
                    },
                },
                "trace": {
                    "provider": "sqlite",
                    "sqlite": {
                        "path": "trace.db",
                        "create_parent_dirs": True,
                        "initialize_schema": True,
                        "journal_mode": "WAL",
                        "synchronous": "NORMAL",
                        "busy_timeout_ms": 5000,
                        "foreign_keys": True,
                        "required": True,
                        "max_event_payload_bytes": 16384,
                        "max_error_detail_bytes": 1024,
                        "max_events_per_trace_read": 40,
                        "max_search_results": 25,
                        "store_raw_session_id": True,
                        "store_session_id_hash": False,
                        "store_raw_user_id": True,
                        "store_user_id_hash": False,
                        "capture_request_body": True,
                        "capture_response_body": False,
                        "capture_llm_prompts": False,
                        "capture_llm_completions": True,
                        "capture_tool_payloads": "none",
                        "capture_memory_queries": "summaries_only",
                        "retention": {
                            "enabled": True,
                            "keep_days": 7,
                            "cleanup_batch_size": 200,
                        },
                    },
                },
                "memory": {
                    "provider": "memory_store",
                    "required": False,
                    "memory_store": {
                        "database_path": "memory",
                        "default_scope": "project",
                        "search_limit_default": 5,
                        "search_limit_max": 15,
                        "allow_writes": False,
                    },
                },
            },
        }
    )


def build_tooling_view() -> ValidatedConfigurationView:
    return ValidatedConfigurationView(
        {
            "tooling": {
                "enabled": True,
                "defaults": {
                    "timeout_seconds": 45,
                    "stream_timeout_seconds": 120,
                    "max_retries": 2,
                    "max_argument_bytes": 8192,
                    "max_result_bytes": 131072,
                    "trace_arguments": False,
                    "trace_results": False,
                    "discovery_on_startup": True,
                    "discovery_refresh_seconds": 180,
                },
                "registry": {
                    "allow_discovered_tools": True,
                    "require_configured_allowlist": True,
                    "tools": {
                        "documents.search": {
                            "enabled": True,
                            "mcp_tool_name": "documents.search",
                            "description": "Search indexed documents.",
                            "allowed_for": {
                                "usecases": ["support_chat"],
                                "agents": ["support_agent"],
                                "strategies": ["direct_agent"],
                            },
                            "timeout_seconds": 30,
                            "max_argument_bytes": 4096,
                            "max_result_bytes": 65536,
                            "approval_required": False,
                            "input_schema_override": {
                                "type": "object",
                                "required": ["query"],
                                "properties": {
                                    "query": {"type": "string"},
                                    "limit": {"type": "integer"},
                                },
                            },
                            "tags": ["documents", "search"],
                            "safety_level": "read_only",
                            "extra": {"category": "knowledge"},
                        },
                        "support.lookup_ticket": {
                            "enabled": False,
                            "mcp_tool_name": "support.lookup_ticket",
                            "description": "Lookup a support ticket.",
                            "allowed_for": {
                                "usecases": ["support_chat"],
                                "agents": ["support_agent"],
                                "strategies": ["direct_agent"],
                            },
                            "timeout_seconds": 20,
                            "max_result_bytes": 32768,
                            "approval_required": True,
                            "tags": ["support"],
                            "safety_level": "external_side_effect",
                            "extra": {"category": "support"},
                        },
                    },
                },
            },
            "mcp": {
                "main": {
                    "name": "main_mcp",
                    "enabled": True,
                    "url": "https://mcp.example.local/mcp",
                    "transport": "sse",
                    "timeout_seconds": 45,
                    "stream_timeout_seconds": 120,
                    "tool_discovery_enabled": True,
                    "auth": {
                        "mode": "oauth_client_credentials",
                        "oauth": {
                            "token_url": "https://auth.example.local/oauth/token",
                            "client_id": "tool-client",
                            "client_secret": "super-secret-client-secret",
                            "scopes": ["tools.read", "tools.execute"],
                        },
                    },
                }
            },
        }
    )


def test_validated_config_view_get_require_and_section() -> None:
    view = build_view()

    assert view.get("app.environment") == "local"
    assert view.get("app.missing", "fallback") == "fallback"
    assert view.require("app.active_usecase") == "support_chat"
    assert view.section("llm") == {
        "defaults": {
            "profile": "cloud_fast",
            "timeout_seconds": 60,
            "stream_timeout_seconds": 90,
            "max_retries": 2,
            "trace_prompts": False,
            "trace_completions": True,
        },
        "providers": {
            "openai": {
                "type": "openai",
                "enabled": True,
                "base_url": "https://api.openai.example/v1",
                "api_key": "top-secret-key",
                "timeout_seconds": 55,
                "stream_timeout_seconds": 75,
                "headers": {"Authorization": "Bearer top-secret-key"},
                "extra": {"region": "test"},
            }
        },
        "profiles": {
            "cloud_fast": {
                "enabled": True,
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "temperature": 0.2,
                "top_p": 0.8,
                "max_output_tokens": 1024,
                "max_input_tokens": 4096,
                "max_total_tokens": 8192,
                "timeout_seconds": 45,
                "stream_timeout_seconds": 70,
                "supports_streaming": True,
                "supports_json_schema": True,
                "supports_tool_calling": False,
                "allowed_for": {
                    "usecases": ["support_chat"],
                    "agents": ["support_agent"],
                    "strategies": ["direct_agent"],
                },
                "fallback_profiles": ["local_reasoning"],
                "extra": {"tier": "fast"},
            }
        },
    }


def test_validated_config_view_is_immutable() -> None:
    view = build_view()

    llm_section = view.get("llm")
    fallback_profiles = view.require("llm.profiles.cloud_fast.fallback_profiles")

    assert isinstance(llm_section, Mapping)
    assert fallback_profiles == ("local_reasoning",)

    with pytest.raises(TypeError):
        llm_section["providers"] = {}  # type: ignore[index]

    with pytest.raises(AttributeError):
        fallback_profiles.append("another-profile")  # type: ignore[attr-defined]


def test_validated_config_view_raises_path_safe_errors() -> None:
    view = build_view()

    with pytest.raises(ConfigurationError, match="Missing required config path: app.missing"):
        view.require("app.missing")

    with pytest.raises(ConfigurationError, match="Config path is not a section: app.environment"):
        view.section("app.environment")


def test_validated_config_view_redacted_dump_masks_secrets() -> None:
    view = build_view()

    assert view.as_redacted_dict() == {
        "app": {
            "environment": "local",
            "active_usecase": "support_chat",
        },
        "api": {
            "enabled": True,
            "base_path": "/api/v1",
            "docs_enabled": False,
            "openapi_enabled": False,
            "cors": {
                "enabled": True,
                "allow_origins": [
                    "http://localhost:5000",
                    "https://frontend.example.local",
                ],
                "allow_credentials": REDACTED_VALUE,
                "allow_methods": ["GET", "POST", "OPTIONS"],
                "allow_headers": [
                    "Authorization",
                    "Content-Type",
                    "X-Request-Id",
                    "X-Trace-Id",
                ],
            },
            "request_limits": {
                "max_body_bytes": 8192,
                "max_message_chars": 4096,
                "max_metadata_bytes": 1024,
                "request_timeout_seconds": 30,
                "stream_timeout_seconds": 45,
            },
            "sessions": {
                "accept_client_session_id": True,
                "create_session_when_missing": False,
                "session_id_header": "X-Session-Id",
            },
            "tracing": {
                "accept_client_trace_id": True,
                "response_trace_header": "X-Trace-Id",
                "record_request_received": True,
                "record_response_returned": False,
                "record_validation_errors": True,
            },
            "debug_routes": {
                "enabled": True,
                "require_localhost": True,
                "restart_enabled": True,
                "max_trace_events": 25,
                "max_search_results": 10,
            },
            "sse": {
                "heartbeat_seconds": 5,
                "send_trace_id_event": False,
                "send_metadata_events": True,
            },
        },
        "session": {
            "enabled": True,
            "identifiers": {
                "prefix": "session",
                "accept_client_session_id": True,
                "generate_when_missing": False,
                "max_length": 96,
                "allowed_pattern": "^[A-Za-z0-9_.:-]{3,96}$",
            },
            "defaults": {
                "default_user_id": "local_user",
                "default_usecase": "support_chat",
                "default_history_limit": 25,
                "max_history_limit": 100,
                "timezone_metadata_key": "timezone",
            },
            "lifecycle": {
                "create_on_first_chat": True,
                "resume_existing_sessions": True,
                "reject_unknown_client_session_id": False,
                "update_last_seen_on_load": True,
                "save_after_failed_orchestration": True,
                "save_after_cancelled_stream": True,
            },
            "concurrency": {
                "mode": "optimistic_version",
                "conflict_policy": "reject",
                "max_retries": 2,
            },
            "state": {
                "save_on_chat_completion": True,
                "save_on_stream_completion": True,
                "save_on_stream_cancellation": True,
                "save_on_stream_failure": True,
                "save_each_stream_delta": False,
            },
            "history": {
                "enabled": True,
                "include_tool_summaries": False,
                "include_system_messages": False,
                "include_metadata": True,
                "max_message_chars": 2048,
                "redaction_enabled": True,
            },
            "management": {
                "list_enabled": True,
                "delete_enabled": False,
                "default_list_limit": 25,
                "max_list_limit": 100,
            },
            "tracing": {
                "record_session_created": True,
                "record_session_resumed": True,
                "record_session_reset": True,
                "record_state_loaded": True,
                "record_state_saved": True,
                "record_history_returned": False,
                "record_stream_lifecycle": True,
            },
        },
        "llm": {
            "defaults": {
                "profile": "cloud_fast",
                "timeout_seconds": 60,
                "stream_timeout_seconds": 90,
                "max_retries": 2,
                "trace_prompts": False,
                "trace_completions": True,
            },
            "providers": {
                "openai": {
                    "type": "openai",
                    "enabled": True,
                    "base_url": "https://api.openai.example/v1",
                    "api_key": REDACTED_VALUE,
                    "timeout_seconds": 55,
                    "stream_timeout_seconds": 75,
                    "headers": {
                        "Authorization": REDACTED_VALUE,
                    },
                    "extra": {"region": "test"},
                }
            },
            "profiles": {
                "cloud_fast": {
                    "enabled": True,
                    "provider": "openai",
                    "model": "gpt-4.1-mini",
                    "temperature": 0.2,
                    "top_p": 0.8,
                    "max_output_tokens": 1024,
                    "max_input_tokens": 4096,
                    "max_total_tokens": 8192,
                    "timeout_seconds": 45,
                    "stream_timeout_seconds": 70,
                    "supports_streaming": True,
                    "supports_json_schema": True,
                    "supports_tool_calling": False,
                    "allowed_for": {
                        "usecases": ["support_chat"],
                        "agents": ["support_agent"],
                        "strategies": ["direct_agent"],
                    },
                    "fallback_profiles": ["local_reasoning"],
                    "extra": {"tier": "fast"},
                }
            },
        },
        "memory": {
            "enabled": False,
            "provider": "memory_store",
            "required": False,
            "defaults": {
                "default_scope": "project",
                "top_k": 5,
                "include_agent_memories": True,
                "include_document_chunks": True,
                "include_graph_context": False,
                "max_result_chars": 900,
                "max_total_context_chars": 3600,
                "trace_query_capture": "summaries_only",
                "trace_result_content_capture": "none",
            },
            "store": {
                "database": {
                    "path": REDACTED_VALUE,
                    "create_if_missing": True,
                    "schema_version": 2,
                    "embedded_single_process": True,
                },
                "embeddings": {
                    "provider": "fastembed",
                    "model": "BAAI/bge-small-en-v1.5",
                    "dimension": 384,
                    "batch_size": 48,
                    "normalize": True,
                    "dimension_mismatch": "reembed",
                },
                "reranker": {
                    "enabled": False,
                    "provider": "fastembed",
                    "model": "Xenova/ms-marco-MiniLM-L-6-v2",
                    "top_n": 20,
                },
            },
            "chunking": {
                "strategy": "markdown_section",
                "max_tokens": REDACTED_VALUE,
                "overlap_tokens": REDACTED_VALUE,
                "include_heading_path": True,
                "include_frontmatter_in_embedding": False,
                "preserve_code_blocks": True,
                "removed_chunk_policy": "mark_removed",
            },
            "search": {
                "limit_max": 15,
                "vector_top_n": 25,
                "fts_top_n": 20,
                "rrf_k": 50,
                "graph_expansion_enabled": True,
                "graph_expansion_hops": 1,
                "final_top_k": 10,
                "include_component_scores": True,
                "include_debug": False,
            },
            "scoring": {
                "weights": {
                    "reranker": 0.4,
                    "retrieval_fusion": 0.15,
                    "vector": 0.12,
                    "full_text": 0.08,
                    "temporal": 0.08,
                    "importance": 0.06,
                    "confidence": 0.04,
                    "graph": 0.04,
                    "user_rating": 0.03,
                },
            },
            "lifecycle": {
                "allow_writes": False,
                "default_ttl_days": None,
                "contradiction_policy": "keep_both_mark_conflict",
                "supersede_policy": "mark_previous_superseded",
                "require_durable_scope_for_writes": True,
                "allow_session_scope_only_writes": False,
                "require_durable_scope_for_delete_export": True,
            },
            "privacy": {
                "default_sensitivity": "internal",
                "allow_llm_context_default": True,
                "allow_retrieval_default": True,
                "delete_by_scope_requires_confirm": True,
                "enable_export_by_scope": False,
                "enable_delete_by_scope": False,
                "hard_delete_enabled": False,
                "tombstone_on_forget": True,
                "require_policy_approval_for_delete_export": True,
            },
            "health": {
                "deep_check_enabled": False,
            },
        },
        "observability": {
            "log_level": "DEBUG",
            "structured_logging": True,
            "trace_enabled": True,
            "trace_payloads_enabled": False,
            "trace_store_required": True,
            "redact_secrets": True,
            "include_stack_traces_in_logs": False,
            "include_stack_traces_in_traces": False,
            "max_trace_payload_chars": 4096,
            "slow_request_ms": 2500,
            "slow_llm_call_ms": 15000,
            "slow_tool_call_ms": 5000,
            "metrics_enabled": True,
        },
        "health": {
            "expose_config_summary": True,
            "expose_provider_names": True,
            "expose_secret_values": False,
            "include_component_details": True,
        },
        "deployment": {
            "profile": "local",
            "host": "0.0.0.0",
            "port": 8010,
            "public_base_url": "http://localhost:8010",
            "log_dir": "var/log/backend",
            "runtime_dir": "var/run/backend",
            "graceful_shutdown_seconds": 25,
            "metrics": {
                "enabled": True,
                "bind_host": "127.0.0.1",
                "port": 9200,
            },
            "readiness": {
                "enabled": True,
                "bind_host": "127.0.0.1",
                "port": 9201,
            },
        },
        "persistence": {
            "base_dir": "./data",
            "workflow_state": {
                "provider": "sqlite",
                "sqlite": {
                    "path": "workflow_state.db",
                    "create_parent_dirs": True,
                    "initialize_schema": True,
                    "journal_mode": "WAL",
                    "synchronous": "full",
                    "busy_timeout_ms": 5000,
                    "foreign_keys": REDACTED_VALUE,
                    "required": True,
                    "max_state_bytes": 4096,
                    "max_history_messages": 25,
                    "reset_mode": "delete_state_row",
                    "store_user_id": True,
                    "store_user_id_hash": False,
                },
            },
            "trace": {
                "provider": "sqlite",
                "sqlite": {
                    "path": "trace.db",
                    "create_parent_dirs": True,
                    "initialize_schema": True,
                    "journal_mode": "WAL",
                    "synchronous": "NORMAL",
                    "busy_timeout_ms": 5000,
                    "foreign_keys": REDACTED_VALUE,
                    "required": True,
                    "max_event_payload_bytes": 16384,
                    "max_error_detail_bytes": 1024,
                    "max_events_per_trace_read": 40,
                    "max_search_results": 25,
                    "store_raw_session_id": True,
                    "store_session_id_hash": False,
                    "store_raw_user_id": True,
                    "store_user_id_hash": False,
                    "capture_request_body": True,
                    "capture_response_body": False,
                    "capture_llm_prompts": False,
                    "capture_llm_completions": True,
                    "capture_tool_payloads": "none",
                    "capture_memory_queries": "summaries_only",
                    "retention": {
                        "enabled": True,
                        "keep_days": 7,
                        "cleanup_batch_size": 200,
                    },
                },
            },
            "memory": {
                "provider": "memory_store",
                "required": False,
                "memory_store": {
                    "database_path": REDACTED_VALUE,
                    "default_scope": "project",
                    "search_limit_default": 5,
                    "search_limit_max": 15,
                    "allow_writes": False,
                },
            },
        },
    }


def test_validated_config_view_observability_helpers_return_typed_settings() -> None:
    view = build_view()

    expected = ObservabilitySettings(
        log_level="DEBUG",
        structured_logging=True,
        trace_enabled=True,
        trace_payloads_enabled=False,
        trace_store_required=True,
        redact_secrets=True,
        include_stack_traces_in_logs=False,
        include_stack_traces_in_traces=False,
        max_trace_payload_chars=4096,
        slow_request_ms=2500,
        slow_llm_call_ms=15000,
        slow_tool_call_ms=5000,
        metrics_enabled=True,
    )

    assert get_observability_settings(view) == expected
    assert view.observability_settings() == expected


def test_validated_config_view_health_helpers_return_typed_settings() -> None:
    view = build_view()

    expected = HealthSettings(
        expose_config_summary=True,
        expose_provider_names=True,
        expose_secret_values=False,
        include_component_details=True,
    )

    assert get_health_settings(view) == expected
    assert view.health_settings() == expected


def test_validated_config_view_deployment_helpers_return_typed_settings() -> None:
    view = build_view()

    expected = DeploymentSettings(
        profile="local",
        host="0.0.0.0",
        port=8010,
        public_base_url="http://localhost:8010",
        log_dir=(BACKEND_ROOT / "var/log/backend").resolve(),
        runtime_dir=(BACKEND_ROOT / "var/run/backend").resolve(),
        graceful_shutdown_seconds=25,
        metrics=DeploymentMetricsSettings(
            enabled=True,
            bind_host="127.0.0.1",
            port=9200,
        ),
        readiness=DeploymentReadinessSettings(
            enabled=True,
            bind_host="127.0.0.1",
            port=9201,
        ),
    )

    assert get_deployment_settings(view) == expected
    assert view.deployment_settings() == expected


def test_validated_config_view_api_helpers_return_typed_settings() -> None:
    view = build_view()

    expected = ApiSettings(
        enabled=True,
        base_path="/api/v1",
        docs_enabled=False,
        openapi_enabled=False,
        cors=CorsSettings(
            enabled=True,
            allow_origins=(
                "http://localhost:5000",
                "https://frontend.example.local",
            ),
            allow_credentials=True,
            allow_methods=("GET", "POST", "OPTIONS"),
            allow_headers=(
                "Authorization",
                "Content-Type",
                "X-Request-Id",
                "X-Trace-Id",
            ),
        ),
        request_limits=ApiRequestLimitSettings(
            max_body_bytes=8192,
            max_message_chars=4096,
            max_metadata_bytes=1024,
            request_timeout_seconds=30,
            stream_timeout_seconds=45,
        ),
        sessions=ApiSessionSettings(
            accept_client_session_id=True,
            create_session_when_missing=False,
            session_id_header="X-Session-Id",
        ),
        tracing=ApiTracingSettings(
            accept_client_trace_id=True,
            response_trace_header="X-Trace-Id",
            record_request_received=True,
            record_response_returned=False,
            record_validation_errors=True,
        ),
        debug_routes=ApiDebugRoutesSettings(
            enabled=True,
            require_localhost=True,
            restart_enabled=True,
            max_trace_events=25,
            max_search_results=10,
        ),
        sse=ApiSseSettings(
            heartbeat_seconds=5,
            send_trace_id_event=False,
            send_metadata_events=True,
        ),
    )

    assert get_api_settings(view) == expected
    assert view.api_settings() == expected


def test_validated_config_view_session_helpers_return_typed_settings() -> None:
    view = build_view()

    expected = SessionSettings(
        enabled=True,
        identifiers=SessionIdentifierSettings(
            prefix="session",
            accept_client_session_id=True,
            generate_when_missing=False,
            max_length=96,
            allowed_pattern="^[A-Za-z0-9_.:-]{3,96}$",
        ),
        defaults=SessionDefaultsSettings(
            default_user_id="local_user",
            default_usecase="support_chat",
            default_history_limit=25,
            max_history_limit=100,
            timezone_metadata_key="timezone",
        ),
        lifecycle=SessionLifecycleSettings(
            create_on_first_chat=True,
            resume_existing_sessions=True,
            reject_unknown_client_session_id=False,
            update_last_seen_on_load=True,
            save_after_failed_orchestration=True,
            save_after_cancelled_stream=True,
        ),
        concurrency=SessionConcurrencySettings(
            mode="optimistic_version",
            conflict_policy="reject",
            max_retries=2,
        ),
        state=SessionStateSettings(
            save_on_chat_completion=True,
            save_on_stream_completion=True,
            save_on_stream_cancellation=True,
            save_on_stream_failure=True,
            save_each_stream_delta=False,
        ),
        history=SessionHistorySettings(
            enabled=True,
            include_tool_summaries=False,
            include_system_messages=False,
            include_metadata=True,
            max_message_chars=2048,
            redaction_enabled=True,
        ),
        management=SessionManagementSettings(
            list_enabled=True,
            delete_enabled=False,
            default_list_limit=25,
            max_list_limit=100,
        ),
        tracing=SessionTracingSettings(
            record_session_created=True,
            record_session_resumed=True,
            record_session_reset=True,
            record_state_loaded=True,
            record_state_saved=True,
            record_history_returned=False,
            record_stream_lifecycle=True,
        ),
    )

    assert get_session_settings(view) == expected
    assert view.session_settings() == expected


def test_validated_config_view_visualization_helpers_return_typed_settings() -> None:
    view = ValidatedConfigurationView(
        {
            "visualization": {
                "enabled": True,
                "default_renderer": "echarts",
                "allowed_renderers": ["echarts"],
                "artifact_spec_version": "1.0",
                "allowed_chart_types": ["bar", "line", "table"],
                "aliases": {
                    "bar graph": "bar",
                    "trend chart": "line",
                },
                "limits": {
                    "max_rows_inline": 120,
                    "max_rows_artifact_store": 800,
                    "max_series": 6,
                    "max_categories": 24,
                    "max_artifact_bytes": 65536,
                },
                "sample_data": {
                    "enabled": True,
                    "require_explicit_opt_in": True,
                    "max_rows": 12,
                },
                "context_summary": {
                    "enabled": True,
                    "mode": "summary_only",
                    "max_tokens_per_chart_summary": 400,
                    "max_chart_summaries_per_session_context": 4,
                    "max_total_visualization_context_tokens": 1200,
                    "include_data_ref": True,
                    "include_aggregate_stats": True,
                    "include_extrema": True,
                    "include_trend_summary": False,
                    "include_sample_rows": False,
                    "max_sample_rows": 0,
                    "eviction_policy": "most_recent_relevant",
                    "allow_full_dataset_in_context": False,
                },
                "artifact_store": {
                    "enabled": True,
                    "provider": "sqlite",
                    "ttl_seconds": 7200,
                    "allow_reference_data_mode": True,
                    "public_retrieval_enabled": True,
                    "retrieval_endpoint": "/artifacts/{artifact_id}",
                    "exact_followup_retrieval_enabled": True,
                },
                "history_replay": {
                    "enabled": True,
                    "prefer_inline": True,
                    "max_artifacts_per_message": 2,
                    "max_inline_artifact_bytes": 32768,
                    "max_total_bytes_per_message": 98304,
                },
                "safe_metadata_allowlist": ["source", "source_agent"],
            }
        }
    )

    expected = VisualizationSettings(
        enabled=True,
        default_renderer="echarts",
        allowed_renderers=("echarts",),
        artifact_spec_version="1.0",
        allowed_chart_types=("bar", "line", "table"),
        aliases={
            "bar graph": "bar",
            "trend chart": "line",
        },
        safe_metadata_allowlist=("source", "source_agent"),
        limits=VisualizationLimitsSettings(
            max_rows_inline=120,
            max_rows_artifact_store=800,
            max_series=6,
            max_categories=24,
            max_artifact_bytes=65536,
        ),
        sample_data=VisualizationSampleDataSettings(
            enabled=True,
            require_explicit_opt_in=True,
            max_rows=12,
        ),
        context_summary=VisualizationContextSummarySettings(
            enabled=True,
            mode="summary_only",
            max_tokens_per_chart_summary=400,
            max_chart_summaries_per_session_context=4,
            max_total_visualization_context_tokens=1200,
            include_data_ref=True,
            include_aggregate_stats=True,
            include_extrema=True,
            include_trend_summary=False,
            include_sample_rows=False,
            max_sample_rows=0,
            eviction_policy="most_recent_relevant",
            allow_full_dataset_in_context=False,
        ),
        artifact_store=VisualizationArtifactStoreSettings(
            enabled=True,
            provider="sqlite",
            ttl_seconds=7200,
            allow_reference_data_mode=True,
            public_retrieval_enabled=True,
            retrieval_endpoint="/artifacts/{artifact_id}",
            exact_followup_retrieval_enabled=True,
            sqlite=VisualizationArtifactStoreSqliteSettings(
                path=resolve_data_path(
                    "visualization_artifacts.db",
                    base_dir=resolve_backend_path("data"),
                ),
                create_parent_dirs=True,
                initialize_schema=True,
                journal_mode="WAL",
                synchronous="NORMAL",
                busy_timeout_ms=5000,
                foreign_keys=True,
                required=True,
            ),
        ),
        history_replay=VisualizationHistoryReplaySettings(
            enabled=True,
            prefer_inline=True,
            max_artifacts_per_message=2,
            max_inline_artifact_bytes=32768,
            max_total_bytes_per_message=98304,
        ),
    )

    assert get_visualization_settings(view) == expected
    assert view.visualization_settings() == expected


def test_validated_config_view_llm_helpers_return_typed_settings() -> None:
    view = build_view()

    expected = LLMSettings(
        defaults=LLMDefaultsSettings(
            profile="cloud_fast",
            timeout_seconds=60,
            stream_timeout_seconds=90,
            max_retries=2,
            trace_prompts=False,
            trace_completions=True,
        ),
        providers={
            "openai": LLMProviderSettings(
                name="openai",
                type="openai",
                enabled=True,
                base_url="https://api.openai.example/v1",
                endpoint=None,
                api_key="top-secret-key",
                auth_header=None,
                auth_token=None,
                timeout_seconds=55,
                stream_timeout_seconds=75,
                headers={"Authorization": "Bearer top-secret-key"},
                extra={"region": "test"},
            )
        },
        profiles={
            "cloud_fast": LLMProfileSettings(
                name="cloud_fast",
                enabled=True,
                provider="openai",
                model="gpt-4.1-mini",
                temperature=0.2,
                top_p=0.8,
                max_output_tokens=1024,
                max_input_tokens=4096,
                max_total_tokens=8192,
                timeout_seconds=45,
                stream_timeout_seconds=70,
                supports_streaming=True,
                supports_json_schema=True,
                supports_tool_calling=False,
                allowed_for=LLMProfileAllowlistSettings(
                    usecases=("support_chat",),
                    agents=("support_agent",),
                    strategies=("direct_agent",),
                ),
                fallback_profiles=("local_reasoning",),
                extra={"tier": "fast"},
            )
        },
    )

    assert get_llm_settings(view) == expected
    assert view.llm_settings() == expected


def test_validated_config_view_tooling_helpers_return_typed_settings() -> None:
    view = build_tooling_view()

    expected = ToolingSettings(
        enabled=True,
        defaults=ToolingDefaultsSettings(
            timeout_seconds=45,
            stream_timeout_seconds=120,
            max_retries=2,
            max_argument_bytes=8192,
            max_result_bytes=131072,
            trace_arguments=False,
            trace_results=False,
            discovery_on_startup=True,
            discovery_refresh_seconds=180,
        ),
        mcp_server=MCPServerSettings(
            name="main_mcp",
            enabled=True,
            endpoint="https://mcp.example.local/mcp",
            transport="sse",
            timeout_seconds=45,
            stream_timeout_seconds=120,
            auth=MCPAuthSettings(
                mode="oauth_client_credentials",
                token=None,
                jwt=None,
                token_url="https://auth.example.local/oauth/token",
                client_id="tool-client",
                client_secret="super-secret-client-secret",
                scopes=("tools.read", "tools.execute"),
            ),
            tool_discovery_enabled=True,
        ),
        registry=ToolRegistrySettings(
            allow_discovered_tools=True,
            require_configured_allowlist=True,
            tools={
                "documents.search": ToolDefinitionSettings(
                    name="documents.search",
                    enabled=True,
                    mcp_tool_name="documents.search",
                    description="Search indexed documents.",
                    allowed_for=ToolAllowedForSettings(
                        usecases=("support_chat",),
                        agents=("support_agent",),
                        strategies=("direct_agent",),
                    ),
                    timeout_seconds=30,
                    max_argument_bytes=4096,
                    max_result_bytes=65536,
                    approval_required=False,
                    input_schema_override={
                        "type": "object",
                        "required": ["query"],
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                    },
                    output_schema_override=None,
                    tags=("documents", "search"),
                    safety_level="read_only",
                    extra={"category": "knowledge"},
                ),
                "support.lookup_ticket": ToolDefinitionSettings(
                    name="support.lookup_ticket",
                    enabled=False,
                    mcp_tool_name="support.lookup_ticket",
                    description="Lookup a support ticket.",
                    allowed_for=ToolAllowedForSettings(
                        usecases=("support_chat",),
                        agents=("support_agent",),
                        strategies=("direct_agent",),
                    ),
                    timeout_seconds=20,
                    max_argument_bytes=None,
                    max_result_bytes=32768,
                    approval_required=True,
                    input_schema_override=None,
                    output_schema_override=None,
                    tags=("support",),
                    safety_level="external_side_effect",
                    extra={"category": "support"},
                ),
            },
        ),
    )

    assert get_tooling_settings(view) == expected
    assert view.tooling_settings() == expected


def test_validated_config_view_redacted_dump_masks_tooling_auth_secrets() -> None:
    redacted = build_tooling_view().as_redacted_dict()

    assert redacted["mcp"]["main"]["auth"]["mode"] == "oauth_client_credentials"
    assert redacted["mcp"]["main"]["auth"]["oauth"]["client_secret"] == REDACTED_VALUE


def test_validated_config_view_memory_helpers_return_typed_settings() -> None:
    view = build_view()

    expected = MemorySettings(
        enabled=False,
        provider="memory_store",
        required=False,
        defaults=MemoryDefaultsSettings(
            default_scope="project",
            top_k=5,
            include_agent_memories=True,
            include_document_chunks=True,
            include_graph_context=False,
            max_result_chars=900,
            max_total_context_chars=3600,
            trace_query_capture="summaries_only",
            trace_result_content_capture="none",
        ),
        store=MemoryStoreViewSettings(
            config_path=None,
            database=MemoryStoreDatabaseSettings(
                path=resolve_data_path("memory", base_dir=resolve_backend_path("./data")),
                create_if_missing=True,
                schema_version=2,
                embedded_single_process=True,
            ),
            embeddings=MemoryEmbeddingsSettings(
                provider="fastembed",
                model="BAAI/bge-small-en-v1.5",
                model_version=None,
                dimension=384,
                batch_size=48,
                normalize=True,
                dimension_mismatch="reembed",
            ),
            reranker=MemoryRerankerSettings(
                enabled=False,
                provider="fastembed",
                model="Xenova/ms-marco-MiniLM-L-6-v2",
                model_version=None,
                top_n=20,
            ),
        ),
        chunking=MemoryChunkingSettings(
            strategy="markdown_section",
            max_tokens=320,
            overlap_tokens=40,
            include_heading_path=True,
            include_frontmatter_in_embedding=False,
            preserve_code_blocks=True,
            removed_chunk_policy="mark_removed",
        ),
        search=MemorySearchSettings(
            limit_max=15,
            vector_top_n=25,
            fts_top_n=20,
            rrf_k=50,
            graph_expansion_enabled=True,
            graph_expansion_hops=1,
            final_top_k=10,
            include_component_scores=True,
            include_debug=False,
        ),
        scoring=MemoryScoringSettings(
            weights=MemoryScoringWeightsSettings(
                reranker=0.4,
                retrieval_fusion=0.15,
                vector=0.12,
                full_text=0.08,
                temporal=0.08,
                importance=0.06,
                confidence=0.04,
                graph=0.04,
                user_rating=0.03,
            )
        ),
        lifecycle=MemoryLifecycleSettings(
            allow_writes=False,
            default_ttl_days=None,
            contradiction_policy="keep_both_mark_conflict",
            supersede_policy="mark_previous_superseded",
            require_durable_scope_for_writes=True,
            allow_session_scope_only_writes=False,
            require_durable_scope_for_delete_export=True,
        ),
        privacy=MemoryPrivacySettings(
            default_sensitivity="internal",
            allow_llm_context_default=True,
            allow_retrieval_default=True,
            delete_by_scope_requires_confirm=True,
            enable_export_by_scope=False,
            enable_delete_by_scope=False,
            hard_delete_enabled=False,
            tombstone_on_forget=True,
            require_policy_approval_for_delete_export=True,
        ),
        health=MemoryHealthSettings(deep_check_enabled=False),
    )

    assert get_memory_settings(view) == expected
    assert view.memory_settings() == expected


def test_api_session_flags_are_sourced_from_session_settings() -> None:
    view = build_view()

    assert view.api_settings().sessions.accept_client_session_id is True
    assert view.api_settings().sessions.create_session_when_missing is False
    assert (
        view.api_settings().sessions.accept_client_session_id
        == view.session_settings().identifiers.accept_client_session_id
    )
    assert (
        view.api_settings().sessions.create_session_when_missing
        == view.session_settings().identifiers.generate_when_missing
    )


def test_api_debug_restart_flag_loads_from_config() -> None:
    view = build_view()

    assert view.api_settings().debug_routes.restart_enabled is True


def test_session_management_settings_load_from_config() -> None:
    view = build_view()

    assert view.session_settings().management == SessionManagementSettings(
        list_enabled=True,
        delete_enabled=False,
        default_list_limit=25,
        max_list_limit=100,
    )


@pytest.mark.parametrize(
    (
        "override_name",
        "expected_base_path",
        "expected_cors_enabled",
        "expected_max_message_chars",
        "expected_debug_enabled",
        "expected_heartbeat_seconds",
    ),
    [
        ("api_basic.yaml", "", False, 20000, False, 15),
        ("api_streaming_enabled.yaml", "/api/v1", True, 20000, False, 5),
        ("api_debug_traces_enabled.yaml", "", False, 20000, True, 15),
        ("api_small_request_limits.yaml", "", False, 128, False, 15),
        ("api_cors_localhost.yaml", "", True, 20000, False, 15),
    ],
)
def test_api_settings_load_from_fixture_overrides(
    override_name: str,
    expected_base_path: str,
    expected_cors_enabled: bool,
    expected_max_message_chars: int,
    expected_debug_enabled: bool,
    expected_heartbeat_seconds: int,
) -> None:
    parsed = load_validated_config(
        CONFIG_FIXTURES_DIR / "valid_minimal.yaml",
        override_path=CONFIG_FIXTURES_DIR / override_name,
        env={},
    )
    view = ValidatedConfigurationView(parsed.model_dump(mode="python"))
    settings = view.api_settings()

    assert settings.enabled is True
    assert settings.base_path == expected_base_path
    assert settings.cors.enabled is expected_cors_enabled
    assert settings.request_limits.max_message_chars == expected_max_message_chars
    assert settings.debug_routes.enabled is expected_debug_enabled
    assert settings.sse.heartbeat_seconds == expected_heartbeat_seconds


def test_api_settings_fixture_normalizes_base_path_and_origins() -> None:
    parsed = load_validated_config(
        CONFIG_FIXTURES_DIR / "valid_minimal.yaml",
        override_path=CONFIG_FIXTURES_DIR / "api_streaming_enabled.yaml",
        env={},
    )
    view = ValidatedConfigurationView(parsed.model_dump(mode="python"))
    settings = view.api_settings()

    assert settings.base_path == "/api/v1"
    assert settings.cors.allow_origins == (
        "http://localhost:5000",
        "http://127.0.0.1:5000",
    )


@pytest.mark.parametrize(
    (
        "override_name",
        "expected_generate_when_missing",
        "expected_history_enabled",
        "expected_default_usecase",
        "expected_history_chars",
        "expected_max_retries",
    ),
    [
        ("session_basic.yaml", True, False, "default_chat", 4000, 1),
        ("session_history_disabled.yaml", True, False, "default_chat", 1024, 1),
        ("session_history_enabled.yaml", True, True, "default_chat", 2048, 1),
        ("session_reject_unknown_client_id.yaml", True, False, "default_chat", 4000, 1),
        ("session_conflict_reject.yaml", True, False, "default_chat", 4000, 2),
        ("session_streaming.yaml", True, False, "default_chat", 4000, 1),
    ],
)
def test_session_settings_load_from_fixture_overrides(
    override_name: str,
    expected_generate_when_missing: bool,
    expected_history_enabled: bool,
    expected_default_usecase: str,
    expected_history_chars: int,
    expected_max_retries: int,
) -> None:
    parsed = load_validated_config(
        CONFIG_FIXTURES_DIR / "valid_minimal.yaml",
        override_path=CONFIG_FIXTURES_DIR / override_name,
        env={},
    )
    view = ValidatedConfigurationView(parsed.model_dump(mode="python"))
    settings = view.session_settings()

    assert settings.enabled is True
    assert settings.identifiers.prefix == "session"
    assert settings.identifiers.generate_when_missing is expected_generate_when_missing
    assert settings.defaults.default_usecase == expected_default_usecase
    assert settings.history.enabled is expected_history_enabled
    assert settings.history.max_message_chars == expected_history_chars
    assert settings.concurrency.max_retries == expected_max_retries


@pytest.mark.parametrize(
    (
        "override_name",
        "expected_profile",
        "expected_provider_type",
        "expected_streaming",
        "expected_json_schema",
        "expected_fallbacks",
        "expected_trace_prompts",
        "expected_trace_completions",
    ),
    [
        ("llm_fake_basic.yaml", "fake_basic", "fake", False, False, (), False, False),
        (
            "llm_fake_streaming.yaml",
            "fake_streaming",
            "fake",
            True,
            False,
            (),
            False,
            False,
        ),
        (
            "llm_fake_fallback.yaml",
            "fake_primary",
            "fake",
            True,
            False,
            ("fake_backup",),
            False,
            False,
        ),
        (
            "llm_structured_output.yaml",
            "structured_writer",
            "fake",
            False,
            True,
            (),
            False,
            False,
        ),
        (
            "llm_trace_capture_disabled.yaml",
            "fake_trace_off",
            "fake",
            False,
            False,
            (),
            False,
            False,
        ),
    ],
)
def test_llm_settings_load_from_fixture_overrides(
    override_name: str,
    expected_profile: str,
    expected_provider_type: str,
    expected_streaming: bool,
    expected_json_schema: bool,
    expected_fallbacks: tuple[str, ...],
    expected_trace_prompts: bool,
    expected_trace_completions: bool,
) -> None:
    parsed = load_validated_config(
        CONFIG_FIXTURES_DIR / "valid_minimal.yaml",
        override_path=CONFIG_FIXTURES_DIR / override_name,
        env={},
    )
    view = ValidatedConfigurationView(parsed.model_dump(mode="python"))
    settings = view.llm_settings()

    assert settings.defaults.profile == expected_profile
    assert settings.defaults.trace_prompts is expected_trace_prompts
    assert settings.defaults.trace_completions is expected_trace_completions

    profile = settings.profiles[expected_profile]
    provider = settings.providers[profile.provider]

    assert provider.type == expected_provider_type
    assert profile.supports_streaming is expected_streaming
    assert profile.supports_json_schema is expected_json_schema
    assert profile.fallback_profiles == expected_fallbacks
    assert profile.allowed_for.usecases
    assert profile.allowed_for.agents
    assert profile.allowed_for.strategies


@pytest.mark.parametrize(
    (
        "override_name",
        "expected_enabled",
        "expected_provider",
        "expected_top_k",
        "expected_limit_max",
        "expected_graph_hops",
    ),
    [
        ("memory_disabled.yaml", False, "memory_store", 10, 30, 1),
        ("memory_fake_basic.yaml", True, "fake", 6, 12, 0),
        ("memory_store_basic.yaml", True, "memory_store", 8, 24, 1),
        ("memory_store_markdown_chunking.yaml", True, "memory_store", 7, 14, 1),
    ],
)
def test_memory_settings_load_from_fixture_overrides(
    override_name: str,
    expected_enabled: bool,
    expected_provider: str,
    expected_top_k: int,
    expected_limit_max: int,
    expected_graph_hops: int,
) -> None:
    parsed = load_validated_config(
        CONFIG_FIXTURES_DIR / "valid_minimal.yaml",
        override_path=CONFIG_FIXTURES_DIR / override_name,
        env={},
    )
    view = ValidatedConfigurationView(parsed.model_dump(mode="python"))
    settings = view.memory_settings()

    assert settings.enabled is expected_enabled
    assert settings.provider == expected_provider
    assert settings.defaults.top_k == expected_top_k
    assert settings.search.limit_max == expected_limit_max
    assert settings.search.graph_expansion_hops == expected_graph_hops

    if expected_provider == "memory_store":
        assert settings.store.database.path.is_absolute()
        assert settings.store.database.path.name in {"memory", "memory-basic"}


@pytest.mark.parametrize(
    (
        "override_name",
        "expected_enabled",
        "expected_transport",
        "expected_auth_mode",
        "expected_tool_count",
        "expected_allow_discovered_tools",
    ),
    [
        ("tooling_disabled.yaml", False, "http", "none", 0, True),
        ("tooling_fake_basic.yaml", True, "http", "none", 1, True),
        ("tooling_fake_streaming.yaml", True, "sse", "none", 1, False),
        (
            "tooling_local_mcp_optional.yaml",
            True,
            "http",
            "oauth_client_credentials",
            1,
            True,
        ),
    ],
)
def test_tooling_settings_load_from_fixture_overrides(
    override_name: str,
    expected_enabled: bool,
    expected_transport: str,
    expected_auth_mode: str,
    expected_tool_count: int,
    expected_allow_discovered_tools: bool,
) -> None:
    parsed = load_validated_config(
        CONFIG_FIXTURES_DIR / "valid_minimal.yaml",
        override_path=CONFIG_FIXTURES_DIR / override_name,
        env={},
    )
    view = ValidatedConfigurationView(parsed.model_dump(mode="python"))
    settings = view.tooling_settings()

    assert settings.enabled is expected_enabled
    assert settings.mcp_server.transport == expected_transport
    assert settings.mcp_server.auth.mode == expected_auth_mode
    assert len(settings.registry.tools) == expected_tool_count
    assert settings.registry.allow_discovered_tools is expected_allow_discovered_tools

    if override_name == "tooling_fake_basic.yaml":
        tool = settings.registry.tools["documents.search"]
        assert tool.allowed_for.usecases == ("default_chat",)
        assert tool.input_schema_override == {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
        }

    if override_name == "tooling_local_mcp_optional.yaml":
        assert settings.mcp_server.auth.scopes == ("tools.read", "tools.execute")
        assert settings.registry.tools["support.lookup_ticket"].approval_required is True


def test_validated_config_view_persistence_helpers_return_typed_settings() -> None:
    view = build_view()

    expected = PersistenceSettings(
        base_dir=resolve_backend_path("./data"),
        workflow_state=WorkflowStatePersistenceSettings(
            provider="sqlite",
            required=True,
            sqlite=SqliteWorkflowStateSettings(
                path=resolve_data_path("workflow_state.db", base_dir=resolve_backend_path("./data")),
                create_parent_dirs=True,
                initialize_schema=True,
                journal_mode="WAL",
                synchronous="FULL",
                busy_timeout_ms=5000,
                foreign_keys=True,
                required=True,
                max_state_bytes=4096,
                max_history_messages=25,
                reset_mode="delete_state_row",
                store_user_id=True,
                store_user_id_hash=False,
            ),
        ),
        trace=TracePersistenceSettings(
            provider="sqlite",
            required=True,
            sqlite=SqliteTraceStoreSettings(
                path=resolve_data_path("trace.db", base_dir=resolve_backend_path("./data")),
                create_parent_dirs=True,
                initialize_schema=True,
                journal_mode="WAL",
                synchronous="NORMAL",
                busy_timeout_ms=5000,
                foreign_keys=True,
                required=True,
                max_event_payload_bytes=16384,
                max_error_detail_bytes=1024,
                max_events_per_trace_read=40,
                max_search_results=25,
                store_raw_session_id=True,
                store_session_id_hash=False,
                store_raw_user_id=True,
                store_user_id_hash=False,
                capture_request_body=True,
                capture_response_body=False,
                capture_llm_prompts=False,
                capture_llm_completions=True,
                capture_tool_payloads="none",
                capture_memory_queries="summaries_only",
                retention_enabled=True,
                retention_keep_days=7,
                retention_cleanup_batch_size=200,
            ),
        ),
        memory=MemoryPersistenceSettings(
            provider="memory_store",
            required=False,
            memory_store=MemoryStoreSettings(
                config_path=None,
                database_path=resolve_data_path("memory", base_dir=resolve_backend_path("./data")),
                schema_version=2,
                default_scope="project",
                search_limit_default=5,
                search_limit_max=15,
                allow_writes=False,
                embedding_batch_size=48,
                embedding_dimension_mismatch="reembed",
                reranker_enabled=False,
                reranker_top_n=20,
                retrieval_vector_top_n=25,
                retrieval_fts_top_n=20,
                retrieval_rrf_k=50,
                chunking_max_tokens=320,
                chunking_overlap_tokens=40,
                chunking_include_frontmatter_in_embedding=False,
                scoring_weight_reranker=0.4,
                scoring_weight_vector=0.12,
                scoring_weight_temporal=0.08,
                scoring_weight_graph=0.04,
                scoring_weight_user_rating=0.03,
            ),
        ),
    )

    assert view.persistence_settings() == expected


@pytest.mark.parametrize("cwd", [BACKEND_ROOT.parent, BACKEND_ROOT])
def test_validated_config_view_persistence_paths_are_backend_root_relative(
    monkeypatch: pytest.MonkeyPatch,
    cwd: Path,
) -> None:
    monkeypatch.chdir(cwd)

    config = load_validated_config(TRACE_FIXTURE_PATH, env={})
    view = ValidatedConfigurationView(config.model_dump(mode="python"))
    settings = view.persistence_settings()

    assert settings.base_dir == resolve_backend_path("data/trace-phase1")
    assert settings.workflow_state.sqlite is not None
    assert settings.workflow_state.sqlite.path == resolve_backend_path(
        "data/trace-phase1/sessions/workflow_state.db"
    )
    assert settings.trace.sqlite is not None
    assert settings.trace.sqlite.path == resolve_backend_path(
        "data/trace-phase1/traces/trace.db"
    )
    assert settings.trace.sqlite.max_event_payload_bytes == 32768


def build_orchestration_view() -> ValidatedConfigurationView:
    return ValidatedConfigurationView(
        {
            "app": {
                "environment": "local",
                "active_usecase": "support_chat",
            },
            "session": {
                "defaults": {
                    "default_usecase": "support_chat",
                }
            },
            "orchestration": {
                "enabled": True,
                "defaults": {
                    "strategy": "direct_agent",
                    "fallback_strategy": "direct_agent",
                    "max_steps": 8,
                    "max_tool_calls": 4,
                    "max_memory_searches": 3,
                    "max_memory_writes": 1,
                    "max_llm_calls": 6,
                    "max_tool_loop_iterations": 3,
                    "max_context_bytes": 64000,
                    "max_turn_duration_seconds": 120,
                    "max_stream_duration_seconds": 300,
                    "emit_step_events": True,
                    "emit_tool_events": True,
                    "emit_memory_events": True,
                    "stream_strategy_events": True,
                    "expose_strategy_metadata": True,
                    "expose_chain_of_thought": False,
                    "save_runtime_snapshots": False,
                    "conversation_context": {
                        "enabled": True,
                        "mode": "summary_then_window",
                        "max_messages": 10,
                        "max_chars": 6000,
                        "include_assistant_messages": True,
                        "summary_threshold_messages": 18,
                        "summary_max_chars": 1200,
                    },
                },
                "strategies": {
                    "direct_agent": {
                        "enabled": True,
                        "type": "direct_agent",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["support_chat"],
                        "llm_profile": "local_reasoning",
                        "memory_enabled": False,
                        "memory_write_enabled": False,
                        "tools_enabled": False,
                        "stream_llm_deltas": True,
                        "expose_strategy_metadata": True,
                    },
                    "retrieval_augmented": {
                        "enabled": True,
                        "type": "retrieval_augmented",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["document_qa"],
                        "llm_profile": "research_reasoning",
                        "memory_enabled": True,
                        "tools_enabled": False,
                        "memory": {
                            "default_limit": 8,
                            "include_document_chunks": True,
                            "include_user_memory": True,
                            "min_score": 0.25,
                            "max_context_items": 6,
                            "max_context_bytes": 24000,
                        },
                        "stream_llm_deltas": True,
                        "expose_strategy_metadata": True,
                    },
                    "bounded_planner": {
                        "enabled": False,
                        "type": "bounded_planner",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["project_plan"],
                        "planner_llm_profile": "planner_reasoning",
                        "executor_llm_profile": "local_reasoning",
                        "memory_enabled": True,
                        "memory_write_enabled": False,
                        "tools_enabled": True,
                        "max_memory_writes": 1,
                        "max_tool_loop_iterations": 2,
                        "max_context_bytes": 48000,
                        "max_plan_steps": 4,
                        "max_execute_steps": 4,
                        "stream_strategy_events": True,
                        "expose_strategy_metadata": True,
                    },
                    "memory_update": {
                        "enabled": True,
                        "type": "memory_update",
                        "default_agent": "support_agent",
                        "allowed_usecases": ["memory_capture"],
                        "llm_profile": "memory_curator",
                        "memory_enabled": True,
                        "memory_write_enabled": True,
                        "max_memory_writes": 1,
                        "candidate_limit": 5,
                        "require_policy_approval": True,
                        "stream_strategy_events": True,
                        "expose_strategy_metadata": True,
                    },
                    "fallback_answer": {
                        "enabled": True,
                        "type": "fallback_answer",
                        "llm_profile": "local_reasoning",
                        "message": "Provide a safe fallback response.",
                        "stream_strategy_events": True,
                        "expose_strategy_metadata": True,
                    },
                },
                "usecases": {
                    "support_chat": {
                        "enabled": True,
                        "display_name": "Support Chat",
                        "description": "Handle standard support chat turns.",
                        "strategy": "direct_agent",
                        "agent": "support_agent",
                        "llm_profile": "local_reasoning",
                        "allowed_agents": ["support_agent"],
                        "allowed_strategies": ["direct_agent", "fallback_answer"],
                        "policy_profile": "default",
                        "tools": {
                            "enabled": False,
                            "allowed_tools": [],
                        },
                    },
                    "document_qa": {
                        "enabled": True,
                        "description": "Answer questions using indexed documents.",
                        "strategy": "retrieval_augmented",
                        "agent": "support_agent",
                        "llm_profile": "research_reasoning",
                        "allowed_agents": ["support_agent"],
                        "allowed_strategies": [
                            "retrieval_augmented",
                            "direct_agent",
                            "fallback_answer",
                        ],
                        "policy_profile": "default",
                        "memory": {
                            "enabled": True,
                            "include_document_chunks": True,
                            "default_limit": 8,
                        },
                    },
                    "memory_capture": {
                        "enabled": True,
                        "description": "Write bounded long-term memory summaries.",
                        "strategy": "memory_update",
                        "agent": "support_agent",
                        "llm_profile": "memory_curator",
                        "allowed_agents": ["support_agent"],
                        "allowed_strategies": ["memory_update", "fallback_answer"],
                        "policy_profile": "default",
                        "memory": {
                            "enabled": True,
                            "include_document_chunks": False,
                            "default_limit": 4,
                        },
                    },
                    "project_plan": {
                        "enabled": True,
                        "description": "Prepare a bounded project plan.",
                        "strategy": "bounded_planner",
                        "agent": "support_agent",
                        "llm_profile": "planner_reasoning",
                        "allowed_agents": ["support_agent"],
                        "allowed_strategies": ["bounded_planner", "fallback_answer"],
                        "policy_profile": "default",
                        "tools": {
                            "enabled": True,
                            "allowed_tools": [],
                        },
                    },
                },
            },
        }
    )


def test_validated_config_view_orchestration_helpers_return_typed_settings() -> None:
    view = build_orchestration_view()

    settings = view.orchestration_settings()

    assert isinstance(settings, OrchestrationSettings)
    assert settings.defaults == OrchestrationDefaultsSettings(
        strategy="direct_agent",
        fallback_strategy="direct_agent",
        max_steps=8,
        max_tool_calls=4,
        max_memory_searches=3,
        max_memory_writes=1,
        max_llm_calls=6,
        max_tool_loop_iterations=3,
        max_context_bytes=64000,
        max_turn_duration_seconds=120,
        max_stream_duration_seconds=300,
        emit_step_events=True,
        emit_tool_events=True,
        emit_memory_events=True,
        stream_strategy_events=True,
        expose_strategy_metadata=True,
        expose_chain_of_thought=False,
        save_runtime_snapshots=False,
        conversation_context=ConversationContextSettings(
            enabled=True,
            mode="summary_then_window",
            max_messages=10,
            max_chars=6000,
            include_assistant_messages=True,
            summary_threshold_messages=18,
            summary_max_chars=1200,
        ),
    )

    direct_strategy = settings.strategies["direct_agent"]
    assert isinstance(direct_strategy, StrategySettings)
    assert direct_strategy.type == "direct_agent"
    assert direct_strategy.default_agent == "support_agent"
    assert direct_strategy.allowed_usecases == ("support_chat",)
    assert direct_strategy.tools_enabled is False

    retrieval_strategy = settings.strategies["retrieval_augmented"]
    assert retrieval_strategy.memory_enabled is True
    assert retrieval_strategy.memory.default_limit == 8
    assert retrieval_strategy.memory.include_document_chunks is True
    assert retrieval_strategy.memory.min_score == pytest.approx(0.25)
    assert retrieval_strategy.memory.max_context_items == 6
    assert retrieval_strategy.memory.max_context_bytes == 24000

    planner_strategy = settings.strategies["bounded_planner"]
    assert planner_strategy.type == "bounded_planner"
    assert planner_strategy.planner_llm_profile == "planner_reasoning"
    assert planner_strategy.executor_llm_profile == "local_reasoning"
    assert planner_strategy.max_plan_steps == 4
    assert planner_strategy.max_execute_steps == 4
    assert planner_strategy.max_tool_loop_iterations == 2

    memory_update_strategy = settings.strategies["memory_update"]
    assert memory_update_strategy.type == "memory_update"
    assert memory_update_strategy.memory_write_enabled is True
    assert memory_update_strategy.max_memory_writes == 1
    assert memory_update_strategy.candidate_limit == 5
    assert memory_update_strategy.require_policy_approval is True

    fallback_strategy = settings.strategies["fallback_answer"]
    assert fallback_strategy.type == "fallback_answer"
    assert fallback_strategy.message == "Provide a safe fallback response."

    support_usecase = settings.usecases["support_chat"]
    assert isinstance(support_usecase, UseCaseSettings)
    assert support_usecase.agent == "support_agent"
    assert support_usecase.display_name == "Support Chat"
    assert support_usecase.allowed_strategies == ("direct_agent", "fallback_answer")

    document_qa = settings.usecases["document_qa"]
    assert document_qa.strategy == "retrieval_augmented"
    assert document_qa.memory.enabled is True
    assert document_qa.memory.default_limit == 8

    memory_capture = settings.usecases["memory_capture"]
    assert memory_capture.strategy == "memory_update"
    assert memory_capture.allowed_strategies == ("memory_update", "fallback_answer")


def test_get_orchestration_settings_supports_legacy_compatibility_paths() -> None:
    view = ValidatedConfigurationView(
        {
            "app": {
                "active_usecase": "support_chat",
            },
            "usecases": {
                "support_chat": {
                    "enabled": True,
                    "strategy": "direct_agent",
                    "default_agent": "support_agent",
                    "allowed_agents": ["support_agent"],
                    "policy_profile": "default",
                        "memory": {
                            "enabled": True,
                            "include_document_chunks": True,
                            "default_limit": 8,
                            "allowed_project_ids": ["arch_docs", "design_docs"],
                            "default_project_id": "arch_docs",
                        },
                }
            },
            "strategies": {
                "direct_agent": {
                    "enabled": True,
                    "type": "direct",
                    "default_agent": "support_agent",
                }
            },
        }
    )

    settings = get_orchestration_settings(view)

    assert settings.defaults.strategy == "direct_agent"
    assert settings.defaults.fallback_strategy == "direct_agent"
    assert settings.strategies["direct_agent"].type == "direct_agent"
    assert settings.usecases["support_chat"].agent == "support_agent"
    assert settings.usecases["support_chat"].memory.allowed_project_ids == (
        "arch_docs",
        "design_docs",
    )
    assert settings.usecases["support_chat"].memory.default_project_id == "arch_docs"


def test_get_agents_settings_resolves_canonical_agent_configuration() -> None:
    view = ValidatedConfigurationView(
        {
            "agents": {
                "defaults": {
                    "enabled": True,
                    "stream_llm_deltas": True,
                    "expose_agent_metadata": True,
                    "strict_prompt_profile_validation": True,
                    "known_prompt_profiles": ["general_assistant_v1"],
                    "max_prompt_context_bytes": 24000,
                    "max_output_chars": 9000,
                    "max_tool_intents": 2,
                    "max_memory_candidates": 4,
                    "max_llm_calls": 1,
                    "max_self_managed_tool_calls": 0,
                    "max_self_managed_memory_searches": 0,
                    "allow_self_managed_tools": False,
                    "allow_self_managed_memory": False,
                    "allow_memory_write": False,
                },
                "plugins": {
                    "support_agent": {
                        "enabled": True,
                        "type": "general_assistant",
                        "display_name": "Support Assistant",
                        "description": "General purpose assistant for direct answers.",
                        "llm_profile": "local_reasoning",
                        "prompt_profile": "general_assistant_v1",
                        "capabilities": {
                            "answer": True,
                            "review": False,
                            "stream": True,
                            "memory_read": False,
                            "memory_write": False,
                            "memory_candidate_extract": False,
                            "tool_intents": True,
                            "tool_execute": False,
                            "self_managed_memory": False,
                            "self_managed_tools": False,
                        },
                        "limits": {
                            "max_prompt_context_bytes": 18000,
                            "max_output_chars": 4000,
                            "max_tool_intents": 1,
                            "max_memory_candidates": 2,
                            "max_llm_calls": 1,
                            "max_self_managed_tool_calls": 0,
                            "max_self_managed_memory_searches": 0,
                        },
                        "context_policy": {
                            "require_context_for_grounded_claims": False,
                            "cite_context_labels": True,
                            "max_context_items": 5,
                            "max_context_bytes": 12000,
                            "allow_untrusted_context_instructions": False,
                        },
                        "allowed_tool_intents": ["documents_search"],
                        "allowed_memory_scopes": ["project", "user"],
                        "memory": {
                            "search_enabled": True,
                            "write_enabled": False,
                            "allowed_project_ids": ["arch_docs", "design_docs"],
                            "default_project_id": "design_docs",
                        },
                        "prompts": {
                            "system_prompt": "You are a configured support assistant.",
                            "developer_prompt": "Prefer short answers.",
                        },
                        "module": "app.testing.fakes.fake_agent",
                        "class_name": "FakeAgent",
                        "metadata": {"tier": "primary"},
                    }
                },
            }
        }
    )

    settings = get_agents_settings(view)

    assert isinstance(settings, AgentsSettings)
    assert settings.enabled is True
    assert settings.strict_prompt_profile_validation is True
    assert settings.known_prompt_profiles == ("general_assistant_v1",)
    assert settings.limits == AgentLimitSettings(
        max_prompt_context_bytes=24000,
        max_output_chars=9000,
        max_tool_intents=2,
        max_memory_candidates=4,
        max_llm_calls=1,
        max_self_managed_tool_calls=0,
        max_self_managed_memory_searches=0,
    )

    agent = settings.plugins["support_agent"]
    assert isinstance(agent, AgentPluginSettings)
    assert agent.type == "general_assistant"
    assert agent.display_name == "Support Assistant"
    assert agent.llm_profile == "local_reasoning"
    assert agent.prompt_profile == "general_assistant_v1"
    assert agent.capabilities == AgentCapabilitySettings(
        answer=True,
        review=False,
        stream=True,
        memory_read=False,
        memory_write=False,
        memory_candidate_extract=False,
        tool_intents=True,
        tool_execute=False,
        self_managed_memory=False,
        self_managed_tools=False,
    )
    assert agent.limits == AgentLimitSettings(
        max_prompt_context_bytes=18000,
        max_output_chars=4000,
        max_tool_intents=1,
        max_memory_candidates=2,
        max_llm_calls=1,
        max_self_managed_tool_calls=0,
        max_self_managed_memory_searches=0,
    )
    assert agent.context_policy == AgentContextPolicySettings(
        require_context_for_grounded_claims=False,
        cite_context_labels=True,
        max_context_items=5,
        max_context_bytes=12000,
        allow_untrusted_context_instructions=False,
    )
    assert agent.allowed_tool_intents == ("documents_search",)
    assert agent.allowed_memory_scopes == ("project", "user")
    assert agent.memory == AgentMemorySettings(
        search_enabled=True,
        write_enabled=False,
        allowed_project_ids=("arch_docs", "design_docs"),
        default_project_id="design_docs",
    )
    assert agent.prompts == AgentPromptOverrideSettings(
        system_prompt="You are a configured support assistant.",
        developer_prompt="Prefer short answers.",
    )
    assert agent.module == "app.testing.fakes.fake_agent"
    assert agent.class_name == "FakeAgent"
    assert agent.metadata == {"tier": "primary"}


def test_get_agents_settings_preserves_legacy_fixture_compatibility() -> None:
    parsed = load_validated_config(CONFIG_FIXTURES_DIR / "valid_minimal.yaml", env={})
    view = ValidatedConfigurationView(parsed.model_dump(mode="python"))

    settings = get_agents_settings(view)

    assert settings.plugins["support_agent"].type == "custom"
    assert settings.plugins["support_agent"].module == "app.testing.fakes.fake_agent"
    assert settings.plugins["support_agent"].class_name == "FakeAgent"
    assert view.require("agents.support_agent.module") == "app.testing.fakes.fake_agent"
    assert view.require("agents.support_agent.class_name") == "FakeAgent"


@pytest.mark.parametrize(
    "override_name",
    ["policy_default_deny.yaml", "policy_usecase_allowed.yaml"],
)
def test_get_policy_settings_reads_policy_fixture_examples(override_name: str) -> None:
    config = load_validated_config(
        CONFIG_FIXTURES_DIR / "valid_minimal.yaml",
        override_path=CONFIG_FIXTURES_DIR / override_name,
        env={},
    )
    view = ValidatedConfigurationView(config.model_dump(mode="python"))

    settings = get_policy_settings(view)

    assert isinstance(settings, PolicySettings)
    assert settings.enabled is True
    assert settings.mode == "enforce"
    assert settings.default_decision == "deny"
    assert settings.fail_closed is True
    assert settings.default_profile in settings.profiles

    profile = settings.profiles[settings.default_profile]
    assert profile.mode == "enforce"
    assert profile.default_decision == "deny"
    assert profile.trace.expose_raw_payloads is False
    assert profile.stream.expose_raw_deltas is False
    assert profile.approval.require_approval_for_write_tools is True


def test_get_policy_settings_returns_typed_nested_policy_sections() -> None:
    view = ValidatedConfigurationView(
        {
            "policy": {
                "enabled": True,
                "mode": "enforce",
                "default_decision": "deny",
                "fail_closed": True,
                "default_profile": "support_policy",
                "visualization": {
                    "enabled": True,
                    "allow_tool_data": True,
                    "allow_reference_data_mode": True,
                    "allowed_chart_types": ["bar", "line"],
                    "max_rows_inline": 250,
                    "max_context_summary_tokens": 450,
                },
                "profiles": {
                    "support_policy": {
                        "mode": "enforce",
                        "default_decision": "deny",
                        "fail_closed": True,
                        "deny_unknown_tools": True,
                        "deny_unknown_llm_profiles": True,
                        "require_memory_scope": True,
                        "allow_memory_writes": False,
                        "tools": {
                            "allowed_tools": ["documents.search"],
                        },
                        "usecases": {
                            "allowed": ["support_chat"],
                        },
                        "strategies": {
                            "allowed": ["direct_agent"],
                        },
                        "agents": {
                            "allowed": ["support_agent"],
                        },
                        "llm": {
                            "allowed_profiles": ["local_reasoning"],
                        },
                        "memory": {
                            "allowed_read_scopes": ["project"],
                        },
                        "approval": {
                            "require_approval_for_write_tools": True,
                        },
                        "fallback": {
                            "allowed_strategies": ["fallback_answer"],
                        },
                        "trace": {
                            "allow_trace": True,
                            "expose_raw_payloads": False,
                        },
                        "stream": {
                            "allow_stream_events": True,
                            "expose_raw_deltas": False,
                        },
                        "visualization": {
                            "allow_memory_data": True,
                            "allowed_chart_types": ["line"],
                            "max_context_summary_tokens": 320,
                        },
                        "capabilities": {
                            "include_policy_profiles": False,
                        },
                        "health": {
                            "include_profile_names": True,
                        },
                        "audit": {
                            "include_reason_codes": True,
                        },
                        "decision_cache": {
                            "enabled": True,
                            "ttl_seconds": 15,
                            "max_entries": 128,
                        },
                    }
                },
            }
        }
    )

    settings = get_policy_settings(view)
    profile = settings.profiles["support_policy"]

    assert settings.default_profile == "support_policy"
    assert profile.usecases.allowed == ("support_chat",)
    assert profile.strategies.allowed == ("direct_agent",)
    assert profile.agents.allowed == ("support_agent",)
    assert profile.llm.allowed_profiles == ("local_reasoning",)
    assert profile.tools.allowed_tools == ("documents.search",)
    assert profile.memory.allowed_read_scopes == ("project",)
    assert profile.fallback.allowed_strategies == ("fallback_answer",)
    assert profile.visualization.enabled is True
    assert profile.visualization.allow_tool_data is True
    assert profile.visualization.allow_memory_data is True
    assert profile.visualization.allow_reference_data_mode is True
    assert profile.visualization.allowed_chart_types == ("line",)
    assert profile.visualization.max_rows_inline == 250
    assert profile.visualization.max_context_summary_tokens == 320
    assert profile.decision_cache.ttl_seconds == 15
    assert profile.decision_cache.max_entries == 128