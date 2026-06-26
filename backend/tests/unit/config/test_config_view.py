from collections.abc import Mapping
from pathlib import Path

import pytest

from app.config.loader import load_validated_config
from app.config.settings import BACKEND_ROOT
from app.config.redaction import REDACTED_VALUE
from app.config.view import (
    ApiDebugRoutesSettings,
    ApiRequestLimitSettings,
    ApiSessionSettings,
    ApiSettings,
    ApiSseSettings,
    ApiTracingSettings,
    CorsSettings,
    HealthSettings,
    ObservabilitySettings,
    ValidatedConfigurationView,
    get_api_settings,
    get_health_settings,
    get_observability_settings,
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
                    "max_trace_events": 25,
                    "max_search_results": 10,
                },
                "sse": {
                    "heartbeat_seconds": 5,
                    "send_trace_id_event": False,
                    "send_metadata_events": True,
                },
            },
            "llm": {
                "providers": {
                    "openai": {
                        "api_key": "top-secret-key",
                    }
                },
                "profiles": {
                    "cloud_fast": {
                        "fallback_profiles": ["local_reasoning"],
                    }
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


def test_validated_config_view_get_require_and_section() -> None:
    view = build_view()

    assert view.get("app.environment") == "local"
    assert view.get("app.missing", "fallback") == "fallback"
    assert view.require("app.active_usecase") == "support_chat"
    assert view.section("llm") == {
        "providers": {"openai": {"api_key": "top-secret-key"}},
        "profiles": {"cloud_fast": {"fallback_profiles": ["local_reasoning"]}},
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
                "max_trace_events": 25,
                "max_search_results": 10,
            },
            "sse": {
                "heartbeat_seconds": 5,
                "send_trace_id_event": False,
                "send_metadata_events": True,
            },
        },
        "llm": {
            "providers": {
                "openai": {
                    "api_key": REDACTED_VALUE,
                }
            },
            "profiles": {
                "cloud_fast": {
                    "fallback_profiles": ["local_reasoning"],
                }
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
                    "database_path": "memory",
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
                default_scope="project",
                search_limit_default=5,
                search_limit_max=15,
                allow_writes=False,
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