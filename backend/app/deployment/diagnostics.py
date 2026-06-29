"""Safe deployment startup diagnostics."""

from __future__ import annotations

from typing import Any


def build_safe_deployment_summary(startup_state: Any) -> dict[str, Any]:
    """Build a secret-safe deployment startup summary for logs and health."""

    directories = {
        key: {
            "ready": value.writable,
            "created": value.created,
        }
        for key, value in startup_state.directories.items()
    }
    return {
        "profile": startup_state.profile,
        "config_path_readable": startup_state.config_path_readable,
        "config_override_configured": startup_state.config_override_configured,
        "runtime_paths_valid": startup_state.runtime_paths_valid,
        "local_directory_bootstrap": startup_state.local_directory_bootstrap,
        "created_directory_count": startup_state.created_directory_count,
        "workflow_state_configured": startup_state.workflow_state_configured,
        "trace_configured": startup_state.trace_configured,
        "memory_configured": startup_state.memory_configured,
        "policy_safe": startup_state.policy_safe,
        "required_dependency_configuration_valid": startup_state.required_dependency_configuration_valid,
        "directories": directories,
    }