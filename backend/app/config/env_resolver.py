"""Environment interpolation helpers for backend configuration files."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

from app.contracts.errors import ConfigurationError

_ENV_REFERENCE_PATTERN = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


def has_env_reference(value: str) -> bool:
    """Return whether a string contains at least one environment reference."""

    return _ENV_REFERENCE_PATTERN.search(value) is not None


def resolve_env_references(
    value: Any,
    *,
    env: Mapping[str, str] | None = None,
    path: str = "",
) -> Any:
    """Resolve ${env:VAR} references recursively without leaking values in errors."""

    environment = os.environ if env is None else env

    if isinstance(value, str):
        return _resolve_string(value, env=environment, path=path)

    if isinstance(value, dict):
        return {
            key: resolve_env_references(
                item,
                env=environment,
                path=_join_path(path, str(key)),
            )
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            resolve_env_references(item, env=environment, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]

    if isinstance(value, tuple):
        return tuple(
            resolve_env_references(item, env=environment, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )

    return value


def _resolve_string(value: str, *, env: Mapping[str, str], path: str) -> str:
    def replace(match: re.Match[str]) -> str:
        variable_name = match.group(1)
        default_value = match.group(2)
        resolved_value = env.get(variable_name)

        if resolved_value is None or resolved_value == "":
            if default_value is None:
                config_path = path or "<root>"
                raise ConfigurationError(
                    f"Missing required environment variable '{variable_name}' "
                    f"for config path '{config_path}'."
                )
            return default_value

        return resolved_value

    return _ENV_REFERENCE_PATTERN.sub(replace, value)


def _join_path(path: str, segment: str) -> str:
    if not path:
        return segment
    return f"{path}.{segment}"