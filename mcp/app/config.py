"""Configuration loading and environment interpolation for the MCP server."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.errors import MCPConfigurationError
from app.schemas import AppSettings


ENV_PLACEHOLDER_PATTERN = re.compile(
    r"^\$\{env:(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::(?P<default>[^}]*))?\}$"
)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MCPConfigurationError(f"MCP config file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise MCPConfigurationError(f"Invalid MCP YAML config: {path}") from exc

    if not isinstance(data, dict):
        raise MCPConfigurationError("MCP config root must be a mapping.")

    return data


def _resolve_env_placeholder(value: str) -> str:
    if "${" not in value:
        return value

    match = ENV_PLACEHOLDER_PATTERN.fullmatch(value)
    if match is None:
        raise MCPConfigurationError(f"Malformed environment placeholder: {value!r}")

    env_name = match.group("name")
    default_value = match.group("default")
    resolved = os.environ.get(env_name)

    if resolved is not None:
        return resolved
    if default_value is not None:
        return default_value

    raise MCPConfigurationError(
        f"Required environment variable {env_name!r} is not set for MCP config."
    )


def resolve_env_placeholders(value: object) -> object:
    if isinstance(value, str):
        return _resolve_env_placeholder(value)
    if isinstance(value, Mapping):
        return {str(key): resolve_env_placeholders(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [resolve_env_placeholders(item) for item in value]
    return value


def load_settings(path: Path) -> AppSettings:
    raw_data = load_yaml(path)
    resolved_data = resolve_env_placeholders(raw_data)
    if not isinstance(resolved_data, dict):
        raise MCPConfigurationError("Resolved MCP config root must be a mapping.")

    try:
        return AppSettings.model_validate(resolved_data)
    except ValidationError as exc:
        raise MCPConfigurationError(f"Invalid MCP configuration: {exc}") from exc


def redacted_settings_summary(settings: AppSettings) -> dict[str, Any]:
    return {
        "server": {
            "name": settings.server.name,
            "version": settings.server.version,
            "environment": settings.server.environment,
            "transport": settings.server.transport,
            "path": settings.server.path,
        },
        "runtime": {
            "tools_dir": settings.runtime.tools_dir,
            "discovery_on_startup": settings.runtime.discovery_on_startup,
            "fail_on_required_tool_error": settings.runtime.fail_on_required_tool_error,
            "fail_on_optional_tool_error": settings.runtime.fail_on_optional_tool_error,
            "reload_tools_in_dev": settings.runtime.reload_tools_in_dev,
        },
        "security": {
            "inbound_auth_enabled": settings.security.inbound_auth.enabled,
            "inbound_auth_mode": settings.security.inbound_auth.mode,
            "tls_mode": settings.security.tls.mode,
            "behind_proxy": settings.security.tls.behind_proxy,
            "credential_provider": settings.security.secrets.provider,
            "allowed_env_prefixes": list(settings.security.secrets.allow_tool_env_prefixes),
            "outbound_oauth_clients_configured": len(settings.security.outbound_auth.oauth_clients),
        },
        "observability": {
            "log_level": settings.observability.log_level,
            "json_logs": settings.observability.json_logs,
            "payload_redaction": settings.observability.redact_secrets,
            "max_log_payload_chars": settings.observability.max_log_payload_chars,
        },
        "defaults": {
            "timeout_seconds": settings.defaults.timeout_seconds,
            "max_result_bytes": settings.defaults.max_result_bytes,
            "max_argument_bytes": settings.defaults.max_argument_bytes,
            "max_results": settings.defaults.max_results,
            "rate_limit_enabled": settings.defaults.rate_limit.enabled,
            "per_tool_per_minute": settings.defaults.rate_limit.per_tool_per_minute,
        },
        "tools": {
            name: {
                "enabled": tool.enabled,
                "required": tool.required,
                "config_file": tool.config_file,
            }
            for name, tool in settings.tools.items()
        },
    }