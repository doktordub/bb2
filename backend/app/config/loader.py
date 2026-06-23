"""Backend configuration loading helpers."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from app.contracts.config import ConfigurationLoader
from app.config.env_resolver import resolve_env_references
from app.config.schemas import BackendConfig
from app.config.settings import BACKEND_ROOT
from app.config.validation import parse_backend_config, validate_backend_config, validate_literal_secrets
from app.config.view import ValidatedConfigurationView
from app.contracts.errors import ConfigurationError


class ConfigLoadError(ConfigurationError):
    """Backward-compatible foundation error for raw config loading failures."""


def resolve_backend_path(path: str | Path | None) -> Path | None:
    """Resolve a path against backend/ so callers do not depend on the shell cwd."""

    if path is None:
        return None

    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = BACKEND_ROOT / candidate

    return candidate.resolve(strict=False)


def load_yaml_mapping(
    path: str | Path | None,
    *,
    required: bool = True,
) -> dict[str, Any]:
    """Load a YAML file and require a mapping at the root."""

    resolved_path = resolve_backend_path(path)
    if resolved_path is None:
        if required:
            raise ConfigurationError("Configuration file path is required.")
        return {}

    if not resolved_path.exists():
        if required:
            raise ConfigurationError(f"Config file does not exist: {resolved_path}")
        return {}

    try:
        with resolved_path.open("r", encoding="utf-8") as handle:
            loaded_data: Any = yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigurationError(f"Failed to read config file: {resolved_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Failed to parse YAML config file: {resolved_path}") from exc

    if loaded_data is None:
        return {}

    if not isinstance(loaded_data, dict):
        raise ConfigurationError(
            f"Config file must contain a YAML mapping at the root: {resolved_path}"
        )

    return dict(loaded_data)


def merge_mappings(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-merge mappings deterministically for config preparation."""

    merged: dict[str, Any] = {key: deepcopy(value) for key, value in base.items()}
    for key, override_value in override.items():
        current_value = merged.get(key)
        if isinstance(current_value, Mapping) and isinstance(override_value, Mapping):
            merged[key] = merge_mappings(current_value, override_value)
            continue
        merged[key] = deepcopy(override_value)
    return merged


def load_prepared_config(
    base_path: str | Path,
    *,
    override_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Read, merge, and resolve config sources before schema validation."""

    base_mapping = load_yaml_mapping(base_path, required=True)
    override_mapping = load_yaml_mapping(override_path, required=False)
    merged_mapping = merge_mappings(base_mapping, override_mapping)
    validate_literal_secrets(merged_mapping)
    resolved_mapping = resolve_env_references(merged_mapping, env=env)

    if not isinstance(resolved_mapping, dict):
        raise ConfigurationError("Resolved configuration must remain a mapping.")

    return resolved_mapping


def load_validated_config(
    base_path: str | Path,
    *,
    override_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> BackendConfig:
    """Load, parse, and cross-validate backend configuration."""

    prepared_mapping = load_prepared_config(base_path, override_path=override_path, env=env)
    parsed_config = parse_backend_config(prepared_mapping)
    validate_backend_config(parsed_config)
    return parsed_config


class YamlConfigurationLoader(ConfigurationLoader):
    """Async configuration loader backed by backend-local YAML files."""

    def __init__(
        self,
        config_path: str | Path,
        *,
        override_path: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._config_path = config_path
        self._override_path = override_path
        self._env = env

    async def load(self) -> ValidatedConfigurationView:
        parsed_config = load_validated_config(
            self._config_path,
            override_path=self._override_path,
            env=self._env,
        )
        return ValidatedConfigurationView(parsed_config.model_dump(mode="python"))


def load_raw_config(
    path: str | None,
    *,
    active_usecase: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    """Load a YAML mapping when available without requiring config during foundation startup."""

    resolved_path = resolve_backend_path(path)
    payload: dict[str, Any] = {
        "active_usecase": active_usecase,
        "source_path": str(resolved_path) if resolved_path is not None else None,
        "config": {},
    }

    if resolved_path is None:
        return payload

    if not resolved_path.exists():
        if strict:
            raise ConfigLoadError(f"Config file does not exist: {resolved_path}")
        return payload

    try:
        payload["config"] = load_yaml_mapping(resolved_path, required=True)
    except ConfigurationError as exc:
        raise ConfigLoadError(str(exc)) from exc

    return payload
