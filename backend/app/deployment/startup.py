"""Deployment startup validation orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.config.settings import Settings
from app.config.view import (
    get_llm_settings,
    get_memory_settings,
    get_policy_settings,
    get_tooling_settings,
)
from app.contracts.config import ConfigurationView
from app.contracts.errors import ConfigurationError
from app.deployment.paths import (
    DeploymentPaths,
    is_local_or_test_profile,
    is_production_like_profile,
    path_is_within,
    path_is_within_backend_root,
    path_targets_source_tree,
    raw_path_has_parent_reference,
    resolve_deployment_paths,
)


@dataclass(frozen=True, slots=True)
class DeploymentDirectoryStatus:
    """Filesystem readiness status for one deployment-owned directory."""

    label: str
    existed: bool
    created: bool
    writable: bool


@dataclass(frozen=True, slots=True)
class DeploymentStartupState:
    """Result of deployment startup validation performed during lifespan startup."""

    profile: str
    paths: DeploymentPaths
    config_path_readable: bool
    config_override_configured: bool
    runtime_paths_valid: bool
    local_directory_bootstrap: bool
    created_directory_count: int
    workflow_state_configured: bool
    trace_configured: bool
    memory_configured: bool
    policy_safe: bool
    required_dependency_configuration_valid: bool
    directories: dict[str, DeploymentDirectoryStatus]


def validate_deployment_startup(
    settings: Settings,
    config: ConfigurationView,
) -> DeploymentStartupState:
    """Validate deployment-owned runtime prerequisites before service startup."""

    paths = resolve_deployment_paths(settings, config)
    profile = paths.profile
    local_bootstrap = is_local_or_test_profile(profile)

    _validate_readable_config_file(
        field_name="APP_CONFIG_PATH",
        raw_value=paths.config_path_raw,
        path=paths.config_path,
        required=True,
    )
    override_exists = _validate_readable_config_file(
        field_name="APP_CONFIG_OVERRIDE_PATH",
        raw_value=paths.config_override_path_raw,
        path=paths.config_override_path,
        required=False,
    )

    directories: dict[str, DeploymentDirectoryStatus] = {}
    directories["data"] = _ensure_directory_ready(
        field_name="persistence.base_dir",
        raw_value=paths.data_dir_raw,
        path=paths.data_dir,
        profile=profile,
        allow_create=local_bootstrap,
        treat_as_write_path=True,
    )
    directories["logs"] = _ensure_directory_ready(
        field_name="deployment.log_dir",
        raw_value=paths.log_dir_raw,
        path=paths.log_dir,
        profile=profile,
        allow_create=local_bootstrap,
        treat_as_write_path=True,
    )
    directories["runtime"] = _ensure_directory_ready(
        field_name="deployment.runtime_dir",
        raw_value=paths.runtime_dir_raw,
        path=paths.runtime_dir,
        profile=profile,
        allow_create=local_bootstrap,
        treat_as_write_path=True,
    )

    workflow_state_configured = paths.workflow_state_path is not None
    if paths.workflow_state_path is not None:
        directories["workflow_state_parent"] = _ensure_file_parent_ready(
            field_name="persistence.workflow_state.sqlite.path",
            raw_value=paths.workflow_state_path_raw,
            file_path=paths.workflow_state_path,
            profile=profile,
            allow_create_parent=local_bootstrap and paths.workflow_state_create_parent_dirs,
            relative_parent=paths.data_dir,
        )

    trace_configured = paths.trace_path is not None
    if paths.trace_path is not None:
        directories["trace_parent"] = _ensure_file_parent_ready(
            field_name="persistence.trace.sqlite.path",
            raw_value=paths.trace_path_raw,
            file_path=paths.trace_path,
            profile=profile,
            allow_create_parent=local_bootstrap and paths.trace_create_parent_dirs,
            relative_parent=paths.data_dir,
        )

    memory_settings = get_memory_settings(config)
    memory_configured = memory_settings.provider not in {"", "disabled", "none"}
    if memory_configured and paths.memory_database_path is not None:
        directories["memory_store"] = _ensure_directory_ready(
            field_name="memory.store.database.path",
            raw_value=paths.memory_database_path_raw,
            path=paths.memory_database_path,
            profile=profile,
            allow_create=local_bootstrap and paths.memory_database_create_if_missing,
            treat_as_write_path=True,
            required=bool(memory_settings.required),
            relative_parent=paths.data_dir
            if paths.memory_database_path_raw is not None
            and not Path(paths.memory_database_path_raw).is_absolute()
            else None,
        )
    _validate_memory_config_path(
        raw_value=paths.memory_config_path_raw,
        path=paths.memory_config_path,
        required=bool(memory_settings.required),
    )

    policy_safe = _validate_policy_safety(profile=profile, config=config)
    _validate_required_dependency_configuration(config)

    return DeploymentStartupState(
        profile=profile,
        paths=paths,
        config_path_readable=True,
        config_override_configured=override_exists,
        runtime_paths_valid=True,
        local_directory_bootstrap=local_bootstrap,
        created_directory_count=sum(1 for value in directories.values() if value.created),
        workflow_state_configured=workflow_state_configured,
        trace_configured=trace_configured,
        memory_configured=memory_configured,
        policy_safe=policy_safe,
        required_dependency_configuration_valid=True,
        directories=directories,
    )


def _validate_readable_config_file(
    *,
    field_name: str,
    raw_value: str,
    path: Path,
    required: bool,
) -> bool:
    if raw_path_has_parent_reference(raw_value):
        raise ConfigurationError(f"{field_name} must not use parent-directory traversal.")

    if not path.exists():
        if required:
            raise ConfigurationError(f"{field_name} must point to a readable file.")
        return False
    if not path.is_file():
        raise ConfigurationError(f"{field_name} must point to a readable file.")
    try:
        with path.open("rb"):
            return True
    except OSError as exc:
        raise ConfigurationError(f"{field_name} must point to a readable file.") from exc


def _validate_memory_config_path(
    *,
    raw_value: str | None,
    path: Path | None,
    required: bool,
) -> None:
    if raw_value is None or path is None:
        return
    if raw_path_has_parent_reference(raw_value):
        raise ConfigurationError("memory.store.config_path must not use parent-directory traversal.")
    if not path.exists():
        if required:
            raise ConfigurationError(
                "memory.store.config_path must point to a readable file when memory is required."
            )
        return
    if not path.is_file():
        raise ConfigurationError("memory.store.config_path must point to a readable file.")
    try:
        with path.open("rb"):
            return
    except OSError as exc:
        raise ConfigurationError("memory.store.config_path must point to a readable file.") from exc


def _ensure_directory_ready(
    *,
    field_name: str,
    raw_value: str | None,
    path: Path,
    profile: str,
    allow_create: bool,
    treat_as_write_path: bool,
    required: bool = True,
    relative_parent: Path | None = None,
) -> DeploymentDirectoryStatus:
    _validate_runtime_path_safety(
        field_name=field_name,
        raw_value=raw_value,
        path=path,
        profile=profile,
        treat_as_write_path=treat_as_write_path,
        relative_parent=relative_parent,
    )

    existed = path.exists()
    created = False
    if existed:
        if not path.is_dir():
            raise ConfigurationError(f"{field_name} must resolve to a directory.")
    else:
        if not required:
            return DeploymentDirectoryStatus(
                label=field_name,
                existed=False,
                created=False,
                writable=False,
            )
        if not allow_create:
            raise ConfigurationError(
                f"{field_name} does not exist and cannot be created automatically in {profile} profile."
            )
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigurationError(f"{field_name} could not be created.") from exc
        created = True

    _probe_directory_writable(path, field_name)
    return DeploymentDirectoryStatus(
        label=field_name,
        existed=existed,
        created=created,
        writable=True,
    )


def _ensure_file_parent_ready(
    *,
    field_name: str,
    raw_value: str | None,
    file_path: Path,
    profile: str,
    allow_create_parent: bool,
    relative_parent: Path | None,
) -> DeploymentDirectoryStatus:
    _validate_runtime_path_safety(
        field_name=field_name,
        raw_value=raw_value,
        path=file_path,
        profile=profile,
        treat_as_write_path=True,
        relative_parent=relative_parent,
    )

    if file_path.exists() and file_path.is_dir():
        raise ConfigurationError(f"{field_name} must resolve to a file path.")

    parent = file_path.parent
    existed = parent.exists()
    created = False
    if existed:
        if not parent.is_dir():
            raise ConfigurationError(f"{field_name} parent directory is invalid.")
    else:
        if not allow_create_parent:
            raise ConfigurationError(
                f"{field_name} parent directory does not exist and cannot be created automatically in {profile} profile."
            )
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigurationError(
                f"{field_name} parent directory could not be created."
            ) from exc
        created = True

    _probe_directory_writable(parent, field_name)
    return DeploymentDirectoryStatus(
        label=f"{field_name}.parent",
        existed=existed,
        created=created,
        writable=True,
    )


def _validate_runtime_path_safety(
    *,
    field_name: str,
    raw_value: str | None,
    path: Path,
    profile: str,
    treat_as_write_path: bool,
    relative_parent: Path | None,
) -> None:
    if raw_path_has_parent_reference(raw_value):
        raise ConfigurationError(f"{field_name} must not use parent-directory traversal.")
    if (
        relative_parent is not None
        and raw_value is not None
        and not Path(raw_value).is_absolute()
        and not path_is_within(path, relative_parent)
    ):
        raise ConfigurationError(
            f"{field_name} must remain within the configured backend data directory when given as a relative path."
        )
    if path_targets_source_tree(path):
        raise ConfigurationError(
            f"{field_name} must not resolve inside backend source package directories."
        )
    if treat_as_write_path and is_production_like_profile(profile) and path_is_within_backend_root(path):
        raise ConfigurationError(
            f"{field_name} must not resolve inside backend/ in {profile} profile."
        )


def _probe_directory_writable(path: Path, field_name: str) -> None:
    probe_path = path / f".deployment-write-check-{uuid4().hex}"
    try:
        with probe_path.open("wb"):
            pass
    except OSError as exc:
        raise ConfigurationError(f"{field_name} must be writable by the backend process.") from exc
    finally:
        if probe_path.exists():
            probe_path.unlink(missing_ok=True)


def _validate_policy_safety(*, profile: str, config: ConfigurationView) -> bool:
    policy = get_policy_settings(config)
    default_profile = policy.profiles.get(policy.default_profile)
    default_profile_safe = (
        default_profile is not None
        and default_profile.enabled
        and default_profile.mode == "enforce"
        and default_profile.default_decision == "deny"
        and default_profile.fail_closed
    )
    policy_safe = (
        policy.enabled
        and policy.mode == "enforce"
        and policy.default_decision == "deny"
        and policy.fail_closed
        and default_profile_safe
    )
    if is_production_like_profile(profile) and not policy_safe:
        raise ConfigurationError(
            "deployment startup requires policy.enabled=true, policy.mode='enforce', policy.default_decision='deny', and policy.fail_closed=true in staging and production profiles."
        )
    return policy_safe


def _validate_required_dependency_configuration(config: ConfigurationView) -> None:
    llm = get_llm_settings(config)
    enabled_llm_profiles = sum(1 for profile in llm.profiles.values() if profile.enabled)
    if enabled_llm_profiles <= 0:
        raise ConfigurationError(
            "deployment startup requires at least one enabled LLM profile."
        )

    tooling = get_tooling_settings(config)
    endpoint = tooling.mcp_server.endpoint
    if tooling.enabled and tooling.mcp_server.enabled and (endpoint is None or endpoint.strip() == ""):
        raise ConfigurationError(
            "deployment startup requires mcp.main.endpoint when tooling is enabled."
        )

    memory = get_memory_settings(config)
    if memory.required and memory.provider == "memory_store":
        config_path = memory.store.config_path
        if config_path is not None and not config_path.exists():
            raise ConfigurationError(
                "deployment startup requires a readable memory.store.config_path when memory is required."
            )