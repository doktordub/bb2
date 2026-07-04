"""YAML-backed built-in agent entrypoint catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from pathlib import Path
import os
from typing import Any

import yaml

from app.config.settings import BACKEND_ROOT
from app.contracts.errors import ConfigurationError

_DEFAULT_BUILTIN_CATALOG_PATH = BACKEND_ROOT / "config" / "agents.catalog.yaml"
_BUILTIN_CATALOG_PATH_ENV = "APP_BUILTIN_AGENTS_CATALOG_PATH"
_REQUIRED_AGENT_TYPES = frozenset(
    {
        "general_assistant",
        "document_qa",
        "tool_using",
        "project_agent",
        "memory_curator",
        "reviewer",
    }
)


class BuiltinAgentCatalogError(ConfigurationError):
    """Built-in-agent catalog loading or validation failed."""


@dataclass(frozen=True, slots=True)
class BuiltinAgentCatalogEntry:
    """One built-in agent entrypoint specification."""

    module: str
    class_name: str


@dataclass(frozen=True, slots=True)
class BuiltinAgentCatalog:
    """Validated built-in agent entrypoints loaded from YAML."""

    source_path: Path
    builtin_agents: Mapping[str, BuiltinAgentCatalogEntry]

    def get(self, agent_type: str) -> BuiltinAgentCatalogEntry | None:
        return self.builtin_agents.get(agent_type)


def clear_builtin_agent_catalog_cache() -> None:
    _load_builtin_agent_catalog_cached.cache_clear()


def load_builtin_agent_catalog(
    path: str | Path | None = None,
    *,
    validate_entrypoints: bool = False,
) -> BuiltinAgentCatalog:
    catalog = _load_builtin_agent_catalog_cached(_resolve_builtin_catalog_path(path))
    if validate_entrypoints:
        _validate_catalog_entrypoints(catalog)
    return catalog


@lru_cache(maxsize=8)
def _load_builtin_agent_catalog_cached(path: Path) -> BuiltinAgentCatalog:
    if not path.exists():
        raise BuiltinAgentCatalogError(
            f"Built-in agent catalog file does not exist: {path}"
        )

    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded: Any = yaml.safe_load(handle)
    except OSError as exc:
        raise BuiltinAgentCatalogError(
            f"Failed to read built-in agent catalog: {path}"
        ) from exc
    except yaml.YAMLError as exc:
        raise BuiltinAgentCatalogError(
            f"Failed to parse built-in agent catalog YAML: {path}"
        ) from exc

    if loaded is None:
        raise BuiltinAgentCatalogError(f"Built-in agent catalog is empty: {path}")
    if not isinstance(loaded, dict):
        raise BuiltinAgentCatalogError(
            f"Built-in agent catalog must contain a YAML mapping at the root: {path}"
        )

    raw_builtin_agents = _require_mapping(
        loaded,
        "builtin_agents",
        location="builtin_agents",
    )
    normalized_builtin_agents: dict[str, BuiltinAgentCatalogEntry] = {}
    for agent_type, raw_entry in raw_builtin_agents.items():
        if not isinstance(agent_type, str) or not agent_type.strip():
            raise BuiltinAgentCatalogError("builtin_agents keys must be non-empty strings.")
        if not isinstance(raw_entry, Mapping):
            raise BuiltinAgentCatalogError(
                f"Expected mapping at builtin_agents.{agent_type}."
            )
        normalized_builtin_agents[agent_type.strip()] = BuiltinAgentCatalogEntry(
            module=_require_text(
                raw_entry,
                "module",
                location=f"builtin_agents.{agent_type}.module",
            ),
            class_name=_require_text(
                raw_entry,
                "class_name",
                location=f"builtin_agents.{agent_type}.class_name",
            ),
        )

    missing_agent_types = sorted(_REQUIRED_AGENT_TYPES - set(normalized_builtin_agents))
    if missing_agent_types:
        raise BuiltinAgentCatalogError(
            "Missing required built-in agent type(s): " + ", ".join(missing_agent_types)
        )

    return BuiltinAgentCatalog(
        source_path=path,
        builtin_agents=normalized_builtin_agents,
    )


def _validate_catalog_entrypoints(catalog: BuiltinAgentCatalog) -> None:
    for agent_type, entry in catalog.builtin_agents.items():
        try:
            module = import_module(entry.module)
        except ImportError as exc:
            raise BuiltinAgentCatalogError(
                f"Unable to import built-in agent module '{entry.module}' for '{agent_type}'."
            ) from exc

        if getattr(module, entry.class_name, None) is None:
            raise BuiltinAgentCatalogError(
                f"Built-in agent class '{entry.class_name}' was not found in module '{entry.module}' for '{agent_type}'."
            )


def _resolve_builtin_catalog_path(path: str | Path | None) -> Path:
    configured = path or os.getenv(_BUILTIN_CATALOG_PATH_ENV)
    candidate = Path(configured) if configured is not None else _DEFAULT_BUILTIN_CATALOG_PATH
    if not candidate.is_absolute():
        candidate = BACKEND_ROOT / candidate
    return candidate.resolve(strict=False)


def _require_mapping(
    mapping: Mapping[str, Any],
    key: str,
    *,
    location: str,
) -> Mapping[str, Any]:
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        raise BuiltinAgentCatalogError(f"Expected mapping at {location}.")
    return value


def _require_text(
    mapping: Mapping[str, Any],
    key: str,
    *,
    location: str,
) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise BuiltinAgentCatalogError(f"Expected non-empty string at {location}.")
    normalized = value.strip()
    if not normalized:
        raise BuiltinAgentCatalogError(f"Expected non-empty string at {location}.")
    return normalized


__all__ = [
    "BuiltinAgentCatalog",
    "BuiltinAgentCatalogEntry",
    "BuiltinAgentCatalogError",
    "clear_builtin_agent_catalog_cache",
    "load_builtin_agent_catalog",
]