"""Typed persistence settings resolved from validated configuration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.contracts.config import ConfigurationView
from app.contracts.errors import ConfigurationError
from app.contracts.state import (
    WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE,
    WORKFLOW_STATE_RESET_MODES,
    WorkflowStateResetMode,
)
from app.persistence.paths import resolve_backend_path, resolve_data_path

DEFAULT_SQLITE_SYNCHRONOUS = "NORMAL"
DEFAULT_WORKFLOW_STATE_MAX_BYTES = 1048576
DEFAULT_WORKFLOW_STATE_MAX_HISTORY_MESSAGES = 50
DEFAULT_TRACE_MAX_EVENT_PAYLOAD_BYTES = 32768
DEFAULT_TRACE_MAX_ERROR_DETAIL_BYTES = 4096
DEFAULT_TRACE_MAX_EVENTS_PER_TRACE_READ = 1000
DEFAULT_TRACE_MAX_SEARCH_RESULTS = 200
DEFAULT_TRACE_RETENTION_KEEP_DAYS = 30
DEFAULT_TRACE_RETENTION_CLEANUP_BATCH_SIZE = 1000
DEFAULT_TRACE_CAPTURE_MODE = "summaries_only"
TRACE_CAPTURE_MODES = frozenset({"none", "summaries_only"})


@dataclass(frozen=True, slots=True)
class SqliteStoreSettings:
    """Resolved SQLite settings shared by persistence adapters."""

    path: Path
    create_parent_dirs: bool
    initialize_schema: bool
    journal_mode: str
    synchronous: str
    busy_timeout_ms: int
    foreign_keys: bool
    required: bool


@dataclass(frozen=True, slots=True)
class SqliteWorkflowStateSettings(SqliteStoreSettings):
    """Resolved SQLite settings for workflow-state persistence."""

    max_state_bytes: int
    max_history_messages: int
    reset_mode: WorkflowStateResetMode
    store_user_id: bool
    store_user_id_hash: bool


@dataclass(frozen=True, slots=True)
class SqliteTraceStoreSettings(SqliteStoreSettings):
    """Resolved SQLite settings for trace persistence."""

    max_event_payload_bytes: int
    max_error_detail_bytes: int
    max_events_per_trace_read: int
    max_search_results: int
    store_raw_session_id: bool
    store_session_id_hash: bool
    store_raw_user_id: bool
    store_user_id_hash: bool
    capture_request_body: bool
    capture_response_body: bool
    capture_llm_prompts: bool
    capture_llm_completions: bool
    capture_tool_payloads: str
    capture_memory_queries: str
    retention_enabled: bool
    retention_keep_days: int
    retention_cleanup_batch_size: int

    @property
    def payload_max_chars(self) -> int:
        """Temporary compatibility alias for the pre-phase-1 payload limit."""

        return self.max_event_payload_bytes


@dataclass(frozen=True, slots=True)
class WorkflowStatePersistenceSettings:
    """Typed workflow-state persistence settings."""

    provider: str
    required: bool
    sqlite: SqliteWorkflowStateSettings | None


@dataclass(frozen=True, slots=True)
class TracePersistenceSettings:
    """Typed trace persistence settings."""

    provider: str
    required: bool
    sqlite: SqliteTraceStoreSettings | None

    @property
    def payload_max_chars(self) -> int | None:
        """Temporary compatibility alias for older trace payload limit lookups."""

        if self.sqlite is None:
            return None
        return self.sqlite.payload_max_chars


@dataclass(frozen=True, slots=True)
class MemoryStoreSettings:
    """Typed memory-store adapter settings."""

    config_path: Path | None
    database_path: Path | None
    default_scope: str
    search_limit_default: int
    search_limit_max: int
    allow_writes: bool


@dataclass(frozen=True, slots=True)
class MemoryPersistenceSettings:
    """Typed memory persistence settings."""

    provider: str
    required: bool
    memory_store: MemoryStoreSettings


@dataclass(frozen=True, slots=True)
class PersistenceSettings:
    """Top-level typed persistence settings for the backend runtime."""

    base_dir: Path
    workflow_state: WorkflowStatePersistenceSettings
    trace: TracePersistenceSettings
    memory: MemoryPersistenceSettings


def get_persistence_settings(config: ConfigurationView) -> PersistenceSettings:
    """Resolve typed persistence settings from validated configuration values."""

    base_dir = _read_base_dir(config)
    return PersistenceSettings(
        base_dir=base_dir,
        workflow_state=_read_workflow_state_settings(config, base_dir),
        trace=_read_trace_settings(config, base_dir),
        memory=_read_memory_settings(config, base_dir),
    )


def _read_base_dir(config: ConfigurationView) -> Path:
    configured = config.get("persistence.base_dir")
    if isinstance(configured, str) and configured.strip():
        return resolve_backend_path(configured.strip())

    app_data_dir = config.get("app.data_dir")
    if isinstance(app_data_dir, str) and app_data_dir.strip():
        return resolve_backend_path(app_data_dir.strip())

    return resolve_backend_path("data")


def _read_workflow_state_settings(
    config: ConfigurationView,
    base_dir: Path,
) -> WorkflowStatePersistenceSettings:
    provider = _read_provider(config, "workflow_state")
    workflow_section = _read_store_section(config, "workflow_state")
    required = _read_store_required(workflow_section, {}, default=True)
    sqlite = None
    if provider == "sqlite":
        base_sqlite = _read_sqlite_settings(
            config,
            store_name="workflow_state",
            default_filename="workflow_state.db",
            base_dir=base_dir,
            default_required=True,
        )
        sqlite_section = _read_mapping(
            workflow_section,
            "sqlite",
            path="persistence.workflow_state.sqlite",
        )
        sqlite = SqliteWorkflowStateSettings(
            path=base_sqlite.path,
            create_parent_dirs=base_sqlite.create_parent_dirs,
            initialize_schema=base_sqlite.initialize_schema,
            journal_mode=base_sqlite.journal_mode,
            synchronous=base_sqlite.synchronous,
            busy_timeout_ms=base_sqlite.busy_timeout_ms,
            foreign_keys=base_sqlite.foreign_keys,
            required=base_sqlite.required,
            max_state_bytes=_read_int(
                sqlite_section,
                "max_state_bytes",
                DEFAULT_WORKFLOW_STATE_MAX_BYTES,
                path="persistence.workflow_state.sqlite.max_state_bytes",
            ),
            max_history_messages=_read_int(
                sqlite_section,
                "max_history_messages",
                DEFAULT_WORKFLOW_STATE_MAX_HISTORY_MESSAGES,
                path="persistence.workflow_state.sqlite.max_history_messages",
            ),
            reset_mode=_read_reset_mode(
                sqlite_section,
                "reset_mode",
                WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE,
                path="persistence.workflow_state.sqlite.reset_mode",
            ),
            store_user_id=_read_bool(
                sqlite_section,
                "store_user_id",
                False,
                path="persistence.workflow_state.sqlite.store_user_id",
            ),
            store_user_id_hash=_read_bool(
                sqlite_section,
                "store_user_id_hash",
                True,
                path="persistence.workflow_state.sqlite.store_user_id_hash",
            ),
        )
        required = sqlite.required
    return WorkflowStatePersistenceSettings(
        provider=provider,
        required=required,
        sqlite=sqlite,
    )


def _read_trace_settings(
    config: ConfigurationView,
    base_dir: Path,
) -> TracePersistenceSettings:
    provider = _read_provider(config, "trace")
    trace_section = _read_store_section(config, "trace")
    required = _read_store_required(trace_section, {}, default=True)
    sqlite = None
    if provider == "sqlite":
        base_sqlite = _read_sqlite_settings(
            config,
            store_name="trace",
            default_filename="trace.db",
            base_dir=base_dir,
            default_required=True,
        )
        sqlite_section = _read_mapping(trace_section, "sqlite", path="persistence.trace.sqlite")
        retention_section = _read_mapping(
            sqlite_section,
            "retention",
            path="persistence.trace.sqlite.retention",
        )
        sqlite = SqliteTraceStoreSettings(
            path=base_sqlite.path,
            create_parent_dirs=base_sqlite.create_parent_dirs,
            initialize_schema=base_sqlite.initialize_schema,
            journal_mode=base_sqlite.journal_mode,
            synchronous=base_sqlite.synchronous,
            busy_timeout_ms=base_sqlite.busy_timeout_ms,
            foreign_keys=base_sqlite.foreign_keys,
            required=base_sqlite.required,
            max_event_payload_bytes=_read_trace_payload_limit(config, sqlite_section),
            max_error_detail_bytes=_read_int(
                sqlite_section,
                "max_error_detail_bytes",
                DEFAULT_TRACE_MAX_ERROR_DETAIL_BYTES,
                path="persistence.trace.sqlite.max_error_detail_bytes",
            ),
            max_events_per_trace_read=_read_int(
                sqlite_section,
                "max_events_per_trace_read",
                DEFAULT_TRACE_MAX_EVENTS_PER_TRACE_READ,
                path="persistence.trace.sqlite.max_events_per_trace_read",
            ),
            max_search_results=_read_int(
                sqlite_section,
                "max_search_results",
                DEFAULT_TRACE_MAX_SEARCH_RESULTS,
                path="persistence.trace.sqlite.max_search_results",
            ),
            store_raw_session_id=_read_bool(
                sqlite_section,
                "store_raw_session_id",
                False,
                path="persistence.trace.sqlite.store_raw_session_id",
            ),
            store_session_id_hash=_read_bool(
                sqlite_section,
                "store_session_id_hash",
                True,
                path="persistence.trace.sqlite.store_session_id_hash",
            ),
            store_raw_user_id=_read_bool(
                sqlite_section,
                "store_raw_user_id",
                False,
                path="persistence.trace.sqlite.store_raw_user_id",
            ),
            store_user_id_hash=_read_bool(
                sqlite_section,
                "store_user_id_hash",
                True,
                path="persistence.trace.sqlite.store_user_id_hash",
            ),
            capture_request_body=_read_bool(
                sqlite_section,
                "capture_request_body",
                False,
                path="persistence.trace.sqlite.capture_request_body",
            ),
            capture_response_body=_read_bool(
                sqlite_section,
                "capture_response_body",
                False,
                path="persistence.trace.sqlite.capture_response_body",
            ),
            capture_llm_prompts=_read_bool(
                sqlite_section,
                "capture_llm_prompts",
                False,
                path="persistence.trace.sqlite.capture_llm_prompts",
            ),
            capture_llm_completions=_read_bool(
                sqlite_section,
                "capture_llm_completions",
                False,
                path="persistence.trace.sqlite.capture_llm_completions",
            ),
            capture_tool_payloads=_read_trace_capture_mode(
                sqlite_section,
                "capture_tool_payloads",
                DEFAULT_TRACE_CAPTURE_MODE,
                path="persistence.trace.sqlite.capture_tool_payloads",
            ),
            capture_memory_queries=_read_trace_capture_mode(
                sqlite_section,
                "capture_memory_queries",
                DEFAULT_TRACE_CAPTURE_MODE,
                path="persistence.trace.sqlite.capture_memory_queries",
            ),
            retention_enabled=_read_bool(
                retention_section,
                "enabled",
                False,
                path="persistence.trace.sqlite.retention.enabled",
            ),
            retention_keep_days=_read_int(
                retention_section,
                "keep_days",
                DEFAULT_TRACE_RETENTION_KEEP_DAYS,
                path="persistence.trace.sqlite.retention.keep_days",
            ),
            retention_cleanup_batch_size=_read_int(
                retention_section,
                "cleanup_batch_size",
                DEFAULT_TRACE_RETENTION_CLEANUP_BATCH_SIZE,
                path="persistence.trace.sqlite.retention.cleanup_batch_size",
            ),
        )
        required = sqlite.required

    return TracePersistenceSettings(
        provider=provider,
        required=required,
        sqlite=sqlite,
    )


def _read_memory_settings(
    config: ConfigurationView,
    base_dir: Path,
) -> MemoryPersistenceSettings:
    provider = _read_provider(config, "memory")
    memory_section = _read_store_section(config, "memory")
    adapter_section = _read_mapping(memory_section, "memory_store", path="persistence.memory.memory_store")
    legacy_section = _read_mapping(memory_section, "config", path="persistence.memory.config")

    config_path = _read_optional_path(
        adapter_section,
        "config_path",
        resolve_with=resolve_backend_path,
        path="persistence.memory.memory_store.config_path",
    )
    database_path = _read_optional_path(
        adapter_section,
        "database_path",
        resolve_with=lambda value: resolve_data_path(value, base_dir=base_dir),
        path="persistence.memory.memory_store.database_path",
    )
    legacy_database_path = _read_optional_path(
        legacy_section,
        "database_path",
        resolve_with=resolve_backend_path,
        path="persistence.memory.config.database_path",
    )

    default_required = False
    if provider not in {"", "memory_store"}:
        default_required = True

    return MemoryPersistenceSettings(
        provider=provider,
        required=_read_store_required(memory_section, adapter_section, default=default_required),
        memory_store=MemoryStoreSettings(
            config_path=config_path,
            database_path=database_path or legacy_database_path,
            default_scope=_read_str(
                adapter_section,
                "default_scope",
                "project",
                path="persistence.memory.memory_store.default_scope",
            ),
            search_limit_default=_read_int(
                adapter_section,
                "search_limit_default",
                10,
                path="persistence.memory.memory_store.search_limit_default",
            ),
            search_limit_max=_read_int(
                adapter_section,
                "search_limit_max",
                30,
                path="persistence.memory.memory_store.search_limit_max",
            ),
            allow_writes=_read_bool(
                adapter_section,
                "allow_writes",
                False,
                path="persistence.memory.memory_store.allow_writes",
            ),
        ),
    )


def _read_trace_payload_limit(
    config: ConfigurationView,
    sqlite_section: Mapping[str, Any],
) -> int:
    if sqlite_section.get("max_event_payload_bytes") is not None:
        return _read_int(
            sqlite_section,
            "max_event_payload_bytes",
            DEFAULT_TRACE_MAX_EVENT_PAYLOAD_BYTES,
            path="persistence.trace.sqlite.max_event_payload_bytes",
        )

    if sqlite_section.get("payload_max_chars") is not None:
        return _read_int(
            sqlite_section,
            "payload_max_chars",
            DEFAULT_TRACE_MAX_EVENT_PAYLOAD_BYTES,
            path="persistence.trace.sqlite.payload_max_chars",
        )

    fallback = _read_optional_config_int(config, "observability.max_trace_payload_chars")
    if fallback is not None:
        return fallback

    return DEFAULT_TRACE_MAX_EVENT_PAYLOAD_BYTES


def _read_provider(config: ConfigurationView, store_name: str) -> str:
    provider = config.get(f"persistence.{store_name}.provider")
    if not isinstance(provider, str) or provider.strip() == "":
        raise ConfigurationError(f"Missing persistence.{store_name}.provider")
    return provider.strip().lower()


def _read_sqlite_settings(
    config: ConfigurationView,
    *,
    store_name: str,
    default_filename: str,
    base_dir: Path,
    default_required: bool,
) -> SqliteStoreSettings:
    store_section = _read_store_section(config, store_name)
    sqlite_section = _read_mapping(
        store_section,
        "sqlite",
        path=f"persistence.{store_name}.sqlite",
    )

    configured_path = _read_optional_path(
        sqlite_section,
        "path",
        resolve_with=lambda value: resolve_data_path(value, base_dir=base_dir),
        path=f"persistence.{store_name}.sqlite.path",
    )
    legacy_path = _read_optional_path(
        store_section,
        "path",
        resolve_with=resolve_backend_path,
        path=f"persistence.{store_name}.path",
    )
    database_path = configured_path or legacy_path or resolve_data_path(default_filename, base_dir=base_dir)

    return SqliteStoreSettings(
        path=database_path,
        create_parent_dirs=_read_bool(
            sqlite_section,
            "create_parent_dirs",
            True,
            path=f"persistence.{store_name}.sqlite.create_parent_dirs",
        ),
        initialize_schema=_read_bool(
            sqlite_section,
            "initialize_schema",
            True,
            path=f"persistence.{store_name}.sqlite.initialize_schema",
        ),
        journal_mode=_read_str(
            sqlite_section,
            "journal_mode",
            "WAL",
            path=f"persistence.{store_name}.sqlite.journal_mode",
        ).upper(),
        synchronous=_read_sqlite_synchronous(
            sqlite_section,
            "synchronous",
            DEFAULT_SQLITE_SYNCHRONOUS,
            path=f"persistence.{store_name}.sqlite.synchronous",
        ),
        busy_timeout_ms=_read_int(
            sqlite_section,
            "busy_timeout_ms",
            5000,
            path=f"persistence.{store_name}.sqlite.busy_timeout_ms",
        ),
        foreign_keys=_read_bool(
            sqlite_section,
            "foreign_keys",
            True,
            path=f"persistence.{store_name}.sqlite.foreign_keys",
        ),
        required=_read_store_required(store_section, sqlite_section, default=default_required),
    )


def _read_store_section(config: ConfigurationView, store_name: str) -> Mapping[str, Any]:
    section = config.get(f"persistence.{store_name}")
    if not isinstance(section, Mapping):
        raise ConfigurationError(f"Config path is not a section: persistence.{store_name}")
    return section


def _read_store_required(
    store_section: Mapping[str, Any],
    nested_section: Mapping[str, Any],
    *,
    default: bool,
) -> bool:
    nested_required = nested_section.get("required")
    if nested_required is not None:
        if not isinstance(nested_required, bool):
            raise ConfigurationError("Invalid config value at required: expected bool.")
        return nested_required

    store_required = store_section.get("required")
    if store_required is not None:
        if not isinstance(store_required, bool):
            raise ConfigurationError("Invalid config value at required: expected bool.")
        return store_required

    return default


def _read_mapping(value: Mapping[str, Any], key: str, *, path: str) -> Mapping[str, Any]:
    candidate = value.get(key)
    if candidate is None:
        return {}
    if not isinstance(candidate, Mapping):
        raise ConfigurationError(f"Invalid config value at {path}: expected mapping.")
    return candidate


def _read_optional_path(
    mapping: Mapping[str, Any],
    key: str,
    *,
    resolve_with: Callable[[str | Path], Path],
    path: str,
) -> Path | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigurationError(f"Invalid config value at {path}: expected non-empty str.")
    return resolve_with(value.strip())


def _read_bool(mapping: Mapping[str, Any], key: str, default: bool, *, path: str) -> bool:
    value = mapping.get(key, default)
    if not isinstance(value, bool):
        raise ConfigurationError(f"Invalid config value at {path}: expected bool.")
    return value


def _read_int(mapping: Mapping[str, Any], key: str, default: int, *, path: str) -> int:
    value = mapping.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigurationError(f"Invalid config value at {path}: expected int.")
    return value


def _read_str(mapping: Mapping[str, Any], key: str, default: str, *, path: str) -> str:
    value = mapping.get(key, default)
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigurationError(f"Invalid config value at {path}: expected non-empty str.")
    return value.strip()


def _read_sqlite_synchronous(
    mapping: Mapping[str, Any],
    key: str,
    default: str,
    *,
    path: str,
) -> str:
    value = _read_str(mapping, key, default, path=path).upper()
    if value not in {"NORMAL", "FULL"}:
        raise ConfigurationError(
            f"Invalid config value at {path}: expected one of NORMAL, FULL."
        )
    return value


def _read_reset_mode(
    mapping: Mapping[str, Any],
    key: str,
    default: str,
    *,
    path: str,
) -> WorkflowStateResetMode:
    value = _read_str(mapping, key, default, path=path).lower()
    if value not in WORKFLOW_STATE_RESET_MODES:
        supported = ", ".join(sorted(WORKFLOW_STATE_RESET_MODES))
        raise ConfigurationError(
            f"Invalid config value at {path}: expected one of {supported}."
        )
    return value


def _read_trace_capture_mode(
    mapping: Mapping[str, Any],
    key: str,
    default: str,
    *,
    path: str,
) -> str:
    value = _read_str(mapping, key, default, path=path).lower()
    if value not in TRACE_CAPTURE_MODES:
        supported = ", ".join(sorted(TRACE_CAPTURE_MODES))
        raise ConfigurationError(
            f"Invalid config value at {path}: expected one of {supported}."
        )
    return value


def _read_optional_config_int(config: ConfigurationView, path: str) -> int | None:
    value = config.get(path, None)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigurationError(f"Invalid config value at {path}: expected int.")
    return value


def _read_config_int(config: ConfigurationView, path: str, default: int) -> int:
    value = config.get(path, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigurationError(f"Invalid config value at {path}: expected int.")
    return value