"""Deployment path resolution and safety helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.config.settings import BACKEND_ROOT, Settings
from app.config.view import get_deployment_settings, get_memory_settings
from app.contracts.config import ConfigurationView
from app.persistence.settings import get_persistence_settings

LOCAL_PROFILE_NAMES = frozenset({"local", "test"})
PRODUCTION_PROFILE_NAMES = frozenset({"staging", "production"})
_SOURCE_DIRECTORY_NAMES = ("app", "config", "tests")
_SOURCE_DIRECTORIES = tuple(BACKEND_ROOT / name for name in _SOURCE_DIRECTORY_NAMES)


@dataclass(frozen=True, slots=True)
class DeploymentPaths:
    """Resolved deployment-owned paths used during startup validation."""

    profile: str
    backend_root: Path
    config_path: Path
    config_path_raw: str
    config_override_path: Path
    config_override_path_raw: str
    data_dir: Path
    data_dir_raw: str
    log_dir: Path
    log_dir_raw: str
    runtime_dir: Path
    runtime_dir_raw: str
    workflow_state_path: Path | None
    workflow_state_path_raw: str | None
    workflow_state_create_parent_dirs: bool
    trace_path: Path | None
    trace_path_raw: str | None
    trace_create_parent_dirs: bool
    memory_config_path: Path | None
    memory_config_path_raw: str | None
    memory_database_path: Path | None
    memory_database_path_raw: str | None
    memory_database_create_if_missing: bool


def resolve_deployment_paths(
    settings: Settings,
    config: ConfigurationView,
) -> DeploymentPaths:
    """Resolve the canonical deployment-owned paths for backend startup."""

    deployment = get_deployment_settings(config)
    persistence = get_persistence_settings(config)
    memory = get_memory_settings(config)
    workflow_sqlite = persistence.workflow_state.sqlite
    trace_sqlite = persistence.trace.sqlite

    return DeploymentPaths(
        profile=deployment.profile,
        backend_root=BACKEND_ROOT,
        config_path=settings.resolved_app_config_path,
        config_path_raw=settings.app_config_path,
        config_override_path=settings.resolved_app_config_override_path,
        config_override_path_raw=settings.app_config_override_path,
        data_dir=persistence.base_dir,
        data_dir_raw=_required_text(
            _read_optional_text(config, "persistence.base_dir"),
            _read_optional_text(config, "app.data_dir"),
            settings.app_data_dir,
            "data",
        ),
        log_dir=deployment.log_dir,
        log_dir_raw=_required_text(
            _read_optional_text(config, "deployment.log_dir"),
            settings.app_log_dir,
            "logs",
        ),
        runtime_dir=deployment.runtime_dir,
        runtime_dir_raw=_required_text(
            _read_optional_text(config, "deployment.runtime_dir"),
            settings.app_runtime_dir,
            "runtime",
        ),
        workflow_state_path=None if workflow_sqlite is None else workflow_sqlite.path,
        workflow_state_path_raw=_first_text(
            _read_optional_text(config, "persistence.workflow_state.sqlite.path"),
            _read_optional_text(config, "persistence.workflow_state.path"),
            "workflow_state.db",
        ),
        workflow_state_create_parent_dirs=(
            True if workflow_sqlite is None else workflow_sqlite.create_parent_dirs
        ),
        trace_path=None if trace_sqlite is None else trace_sqlite.path,
        trace_path_raw=_first_text(
            _read_optional_text(config, "persistence.trace.sqlite.path"),
            _read_optional_text(config, "persistence.trace.path"),
            "trace.db",
        ),
        trace_create_parent_dirs=True if trace_sqlite is None else trace_sqlite.create_parent_dirs,
        memory_config_path=memory.store.config_path,
        memory_config_path_raw=_read_optional_text(
            config,
            "memory.store.config_path",
        ) or _read_optional_text(config, "persistence.memory.memory_store.config_path"),
        memory_database_path=memory.store.database.path,
        memory_database_path_raw=_first_text(
            _read_optional_text(config, "memory.store.database.path"),
            _read_optional_text(config, "persistence.memory.memory_store.database_path"),
            _read_optional_text(config, "persistence.memory.config.database_path"),
            "memory",
        ),
        memory_database_create_if_missing=memory.store.database.create_if_missing,
    )


def is_local_or_test_profile(profile: str) -> bool:
    """Return whether the deployment profile supports local runtime bootstrapping."""

    return profile in LOCAL_PROFILE_NAMES


def is_production_like_profile(profile: str) -> bool:
    """Return whether the deployment profile should behave like a promoted runtime."""

    return profile in PRODUCTION_PROFILE_NAMES


def raw_path_has_parent_reference(raw_path: str | None) -> bool:
    """Return whether a relative config-derived path uses parent traversal."""

    if raw_path is None:
        return False
    if Path(raw_path).is_absolute():
        return False
    return any(part == ".." for part in PurePosixPath(raw_path.replace("\\", "/")).parts)


def path_is_within(path: Path, parent: Path) -> bool:
    """Return whether path resolves under the provided parent directory."""

    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def path_targets_source_tree(path: Path) -> bool:
    """Return whether a write-target path resolves inside backend source directories."""

    return any(path_is_within(path, source_directory) for source_directory in _SOURCE_DIRECTORIES)


def path_is_within_backend_root(path: Path) -> bool:
    """Return whether a path resolves anywhere under backend/."""

    return path_is_within(path, BACKEND_ROOT)


def _read_optional_text(config: ConfigurationView, path: str) -> str | None:
    value = config.get(path)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _first_text(*values: str | None) -> str | None:
    for value in values:
        if value is not None and value.strip() != "":
            return value
    return None


def _required_text(*values: str | None) -> str:
    resolved = _first_text(*values)
    if resolved is None:
        raise ValueError("Expected at least one non-empty path value.")
    return resolved