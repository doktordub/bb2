from __future__ import annotations

from pathlib import Path

import pytest

from app.config.loader import load_validated_config
from app.config.view import ValidatedConfigurationView
from app.persistence.paths import resolve_backend_path
from app.persistence.settings import get_persistence_settings

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "config"


def load_fixture_view(name: str) -> ValidatedConfigurationView:
    config = load_validated_config(FIXTURES_DIR / name, env={})
    return ValidatedConfigurationView(config.model_dump(mode="python"))


def test_persistence_settings_resolve_typed_runtime_values() -> None:
    view = ValidatedConfigurationView(
        {
            "app": {"data_dir": "./data"},
            "observability": {"max_trace_payload_chars": 7000},
            "persistence": {
                "base_dir": "data/runtime",
                "workflow_state": {
                    "provider": "sqlite",
                    "sqlite": {
                        "path": "workflow_state.db",
                        "create_parent_dirs": True,
                        "initialize_schema": False,
                        "journal_mode": "wal",
                        "synchronous": "full",
                        "busy_timeout_ms": 9000,
                        "foreign_keys": False,
                        "required": True,
                        "max_state_bytes": 2048,
                        "max_history_messages": 12,
                        "reset_mode": "delete_state_row",
                        "store_user_id": True,
                        "store_user_id_hash": False,
                    },
                },
                "trace": {
                    "provider": "sqlite",
                    "sqlite": {
                        "path": "trace.db",
                        "synchronous": "full",
                        "max_event_payload_bytes": 16384,
                        "payload_max_chars": 2048,
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
                        "config_path": "config/memory_store.yaml",
                        "database_path": "memory",
                        "default_scope": "project",
                        "search_limit_default": 8,
                        "search_limit_max": 20,
                        "allow_writes": True,
                    },
                },
            },
        }
    )

    settings = get_persistence_settings(view)

    assert settings.base_dir == resolve_backend_path("data/runtime")
    assert settings.workflow_state.sqlite is not None
    assert settings.workflow_state.required is True
    assert settings.workflow_state.sqlite.path == resolve_backend_path("data/runtime/workflow_state.db")
    assert settings.workflow_state.sqlite.initialize_schema is False
    assert settings.workflow_state.sqlite.journal_mode == "WAL"
    assert settings.workflow_state.sqlite.synchronous == "FULL"
    assert settings.workflow_state.sqlite.busy_timeout_ms == 9000
    assert settings.workflow_state.sqlite.foreign_keys is False
    assert settings.workflow_state.sqlite.max_state_bytes == 2048
    assert settings.workflow_state.sqlite.max_history_messages == 12
    assert settings.workflow_state.sqlite.reset_mode == "delete_state_row"
    assert settings.workflow_state.sqlite.store_user_id is True
    assert settings.workflow_state.sqlite.store_user_id_hash is False
    assert settings.trace.sqlite is not None
    assert settings.trace.required is True
    assert settings.trace.sqlite.path == resolve_backend_path("data/runtime/trace.db")
    assert settings.trace.sqlite.synchronous == "FULL"
    assert settings.trace.sqlite.max_event_payload_bytes == 16384
    assert settings.trace.sqlite.payload_max_chars == 16384
    assert settings.trace.sqlite.max_error_detail_bytes == 1024
    assert settings.trace.sqlite.max_events_per_trace_read == 40
    assert settings.trace.sqlite.max_search_results == 25
    assert settings.trace.sqlite.store_raw_session_id is True
    assert settings.trace.sqlite.store_session_id_hash is False
    assert settings.trace.sqlite.store_raw_user_id is True
    assert settings.trace.sqlite.store_user_id_hash is False
    assert settings.trace.sqlite.capture_request_body is True
    assert settings.trace.sqlite.capture_response_body is False
    assert settings.trace.sqlite.capture_llm_prompts is False
    assert settings.trace.sqlite.capture_llm_completions is True
    assert settings.trace.sqlite.capture_tool_payloads == "none"
    assert settings.trace.sqlite.capture_memory_queries == "summaries_only"
    assert settings.trace.sqlite.retention_enabled is True
    assert settings.trace.sqlite.retention_keep_days == 7
    assert settings.trace.sqlite.retention_cleanup_batch_size == 200
    assert settings.memory.memory_store.config_path == resolve_backend_path("config/memory_store.yaml")
    assert settings.memory.memory_store.database_path == resolve_backend_path("data/runtime/memory")
    assert settings.memory.memory_store.search_limit_default == 8
    assert settings.memory.memory_store.search_limit_max == 20
    assert settings.memory.memory_store.allow_writes is True


def test_persistence_settings_preserve_legacy_path_shape() -> None:
    view = ValidatedConfigurationView(
        {
            "app": {"data_dir": "./data"},
            "observability": {"max_trace_payload_chars": 8000},
            "persistence": {
                "workflow_state": {
                    "provider": "sqlite",
                    "path": "./data/workflow_state.db",
                },
                "trace": {
                    "provider": "sqlite",
                    "path": "./data/trace.db",
                },
                "memory": {
                    "provider": "memory_store",
                    "config": {
                        "database_path": "./data/memory",
                    },
                },
            },
        }
    )

    settings = get_persistence_settings(view)

    assert settings.base_dir == resolve_backend_path("./data")
    assert settings.workflow_state.sqlite is not None
    assert settings.workflow_state.required is True
    assert settings.workflow_state.sqlite.path == resolve_backend_path("./data/workflow_state.db")
    assert settings.workflow_state.sqlite.synchronous == "NORMAL"
    assert settings.workflow_state.sqlite.max_state_bytes == 1048576
    assert settings.workflow_state.sqlite.max_history_messages == 50
    assert settings.workflow_state.sqlite.reset_mode == "replace_with_empty_state"
    assert settings.workflow_state.sqlite.store_user_id is False
    assert settings.workflow_state.sqlite.store_user_id_hash is True
    assert settings.trace.sqlite is not None
    assert settings.trace.required is True
    assert settings.trace.sqlite.path == resolve_backend_path("./data/trace.db")
    assert settings.trace.sqlite.synchronous == "NORMAL"
    assert settings.trace.sqlite.max_event_payload_bytes == 8000
    assert settings.trace.payload_max_chars == 8000
    assert settings.memory.memory_store.database_path == resolve_backend_path("./data/memory")


def test_persistence_settings_maps_legacy_trace_payload_alias() -> None:
    view = ValidatedConfigurationView(
        {
            "persistence": {
                "workflow_state": {
                    "provider": "sqlite",
                    "path": "./data/workflow_state.db",
                },
                "trace": {
                    "provider": "sqlite",
                    "sqlite": {
                        "path": "trace.db",
                        "payload_max_chars": 2048,
                    },
                },
                "memory": {
                    "provider": "fake",
                },
            },
        }
    )

    settings = get_persistence_settings(view)

    assert settings.trace.sqlite is not None
    assert settings.trace.sqlite.max_event_payload_bytes == 2048
    assert settings.trace.payload_max_chars == 2048


@pytest.mark.parametrize(
    ("fixture_name", "expected_base_dir", "expected_state_path", "expected_synchronous", "expected_max_state_bytes", "expected_max_history_messages", "expected_reset_mode", "expected_store_user_id", "expected_store_user_id_hash"),
    [
        (
            "workflow_state_sqlite.yaml",
            "data/workflow-phase1",
            "data/workflow-phase1/sessions/workflow_state.db",
            "FULL",
            1048576,
            50,
            "replace_with_empty_state",
            False,
            True,
        ),
        (
            "workflow_state_sqlite_small_max_size.yaml",
            "data/workflow-small",
            "data/workflow-small/workflow_state.db",
            "NORMAL",
            512,
            8,
            "replace_with_empty_state",
            False,
            True,
        ),
        (
            "workflow_state_sqlite_delete_reset.yaml",
            "data/workflow-delete-reset",
            "data/workflow-delete-reset/archive/workflow_state.db",
            "NORMAL",
            8192,
            25,
            "delete_state_row",
            True,
            False,
        ),
    ],
)
def test_persistence_settings_parse_workflow_state_phase1_fixtures(
    fixture_name: str,
    expected_base_dir: str,
    expected_state_path: str,
    expected_synchronous: str,
    expected_max_state_bytes: int,
    expected_max_history_messages: int,
    expected_reset_mode: str,
    expected_store_user_id: bool,
    expected_store_user_id_hash: bool,
) -> None:
    settings = get_persistence_settings(load_fixture_view(fixture_name))

    assert settings.base_dir == resolve_backend_path(expected_base_dir)
    assert settings.workflow_state.sqlite is not None
    assert settings.workflow_state.sqlite.path == resolve_backend_path(expected_state_path)
    assert settings.workflow_state.sqlite.synchronous == expected_synchronous
    assert settings.workflow_state.sqlite.max_state_bytes == expected_max_state_bytes
    assert settings.workflow_state.sqlite.max_history_messages == expected_max_history_messages
    assert settings.workflow_state.sqlite.reset_mode == expected_reset_mode
    assert settings.workflow_state.sqlite.store_user_id is expected_store_user_id
    assert settings.workflow_state.sqlite.store_user_id_hash is expected_store_user_id_hash


def test_persistence_settings_parse_workflow_state_fake_fixture() -> None:
    settings = get_persistence_settings(load_fixture_view("workflow_state_fake.yaml"))

    assert settings.base_dir == resolve_backend_path("data/workflow-fake")
    assert settings.workflow_state.provider == "fake"
    assert settings.workflow_state.required is False
    assert settings.workflow_state.sqlite is None


@pytest.mark.parametrize(
    (
        "fixture_name",
        "expected_base_dir",
        "expected_trace_path",
        "expected_initialize_schema",
        "expected_synchronous",
        "expected_max_event_payload_bytes",
        "expected_max_error_detail_bytes",
        "expected_max_events_per_trace_read",
        "expected_max_search_results",
        "expected_store_raw_session_id",
        "expected_store_session_id_hash",
        "expected_store_raw_user_id",
        "expected_store_user_id_hash",
        "expected_capture_tool_payloads",
        "expected_capture_memory_queries",
        "expected_retention_enabled",
        "expected_retention_keep_days",
        "expected_retention_cleanup_batch_size",
    ),
    [
        (
            "trace_sqlite.yaml",
            "data/trace-phase1",
            "data/trace-phase1/traces/trace.db",
            True,
            "FULL",
            32768,
            4096,
            1000,
            200,
            False,
            True,
            False,
            True,
            "summaries_only",
            "summaries_only",
            False,
            30,
            1000,
        ),
        (
            "trace_sqlite_no_schema_init.yaml",
            "data/trace-no-schema",
            "data/trace-no-schema/deferred/trace.db",
            False,
            "NORMAL",
            16384,
            2048,
            250,
            75,
            False,
            True,
            False,
            True,
            "summaries_only",
            "summaries_only",
            False,
            30,
            1000,
        ),
        (
            "trace_sqlite_small_payload.yaml",
            "data/trace-small-payload",
            "data/trace-small-payload/trace.db",
            True,
            "NORMAL",
            512,
            256,
            25,
            10,
            False,
            True,
            False,
            True,
            "none",
            "none",
            False,
            30,
            1000,
        ),
        (
            "trace_sqlite_retention_enabled.yaml",
            "data/trace-retention",
            "data/trace-retention/history/trace.db",
            True,
            "FULL",
            24576,
            3072,
            300,
            120,
            True,
            False,
            True,
            False,
            "summaries_only",
            "summaries_only",
            True,
            14,
            250,
        ),
    ],
)
def test_persistence_settings_parse_trace_phase1_fixtures(
    fixture_name: str,
    expected_base_dir: str,
    expected_trace_path: str,
    expected_initialize_schema: bool,
    expected_synchronous: str,
    expected_max_event_payload_bytes: int,
    expected_max_error_detail_bytes: int,
    expected_max_events_per_trace_read: int,
    expected_max_search_results: int,
    expected_store_raw_session_id: bool,
    expected_store_session_id_hash: bool,
    expected_store_raw_user_id: bool,
    expected_store_user_id_hash: bool,
    expected_capture_tool_payloads: str,
    expected_capture_memory_queries: str,
    expected_retention_enabled: bool,
    expected_retention_keep_days: int,
    expected_retention_cleanup_batch_size: int,
) -> None:
    settings = get_persistence_settings(load_fixture_view(fixture_name))

    assert settings.base_dir == resolve_backend_path(expected_base_dir)
    assert settings.trace.sqlite is not None
    assert settings.trace.sqlite.path == resolve_backend_path(expected_trace_path)
    assert settings.trace.sqlite.initialize_schema is expected_initialize_schema
    assert settings.trace.sqlite.synchronous == expected_synchronous
    assert settings.trace.sqlite.max_event_payload_bytes == expected_max_event_payload_bytes
    assert settings.trace.sqlite.max_error_detail_bytes == expected_max_error_detail_bytes
    assert settings.trace.sqlite.max_events_per_trace_read == expected_max_events_per_trace_read
    assert settings.trace.sqlite.max_search_results == expected_max_search_results
    assert settings.trace.sqlite.store_raw_session_id is expected_store_raw_session_id
    assert settings.trace.sqlite.store_session_id_hash is expected_store_session_id_hash
    assert settings.trace.sqlite.store_raw_user_id is expected_store_raw_user_id
    assert settings.trace.sqlite.store_user_id_hash is expected_store_user_id_hash
    assert settings.trace.sqlite.capture_tool_payloads == expected_capture_tool_payloads
    assert settings.trace.sqlite.capture_memory_queries == expected_capture_memory_queries
    assert settings.trace.sqlite.retention_enabled is expected_retention_enabled
    assert settings.trace.sqlite.retention_keep_days == expected_retention_keep_days
    assert (
        settings.trace.sqlite.retention_cleanup_batch_size
        == expected_retention_cleanup_batch_size
    )


def test_persistence_settings_parse_trace_fake_fixture() -> None:
    settings = get_persistence_settings(load_fixture_view("trace_fake.yaml"))

    assert settings.base_dir == resolve_backend_path("data/trace-fake")
    assert settings.trace.provider == "fake"
    assert settings.trace.required is False
    assert settings.trace.sqlite is None