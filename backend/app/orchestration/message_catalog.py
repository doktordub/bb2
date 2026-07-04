"""YAML-backed user-facing strategy message catalog."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os
from typing import Any

import yaml

from app.config.settings import BACKEND_ROOT
from app.contracts.errors import ConfigurationError

_DEFAULT_MESSAGES_PATH = BACKEND_ROOT / "config" / "messages.yaml"
_MESSAGES_PATH_ENV = "APP_MESSAGES_CONFIG_PATH"
_REQUIRED_MESSAGE_KEYS: dict[str, tuple[str, ...]] = {
    "fallback_answer": ("default_message",),
    "memory_update": (
        "no_candidate_answer",
        "approval_required_answer",
    ),
}


class MessageCatalogError(ConfigurationError):
    """Message-catalog loading or validation failed."""


@dataclass(frozen=True, slots=True)
class MessageCatalog:
    """Validated strategy messages loaded from YAML."""

    source_path: Path
    messages: Mapping[str, Mapping[str, str]]

    def get_text(self, section: str, key: str) -> str:
        section_mapping = _require_mapping(self.messages, section, location=f"messages.{section}")
        return _require_text(section_mapping, key, location=f"messages.{section}.{key}")


class MessageTemplateService:
    """High-level message lookup service with safe code fallbacks."""

    def __init__(self, catalog: MessageCatalog | None = None) -> None:
        self._catalog = catalog

    def catalog(self) -> MessageCatalog:
        if self._catalog is not None:
            return self._catalog
        return load_message_catalog()

    def get_text(self, section: str, key: str, *, fallback: str) -> str:
        try:
            return self.catalog().get_text(section, key)
        except MessageCatalogError:
            return fallback


def default_message_template_service() -> MessageTemplateService:
    return _default_message_template_service()


def clear_message_catalog_cache() -> None:
    _load_message_catalog_cached.cache_clear()
    _default_message_template_service.cache_clear()


def load_message_catalog(path: str | Path | None = None) -> MessageCatalog:
    resolved_path = _resolve_messages_path(path)
    return _load_message_catalog_cached(resolved_path)


@lru_cache(maxsize=1)
def _default_message_template_service() -> MessageTemplateService:
    return MessageTemplateService()


@lru_cache(maxsize=8)
def _load_message_catalog_cached(path: Path) -> MessageCatalog:
    if not path.exists():
        raise MessageCatalogError(f"Message catalog file does not exist: {path}")

    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded: Any = yaml.safe_load(handle)
    except OSError as exc:
        raise MessageCatalogError(f"Failed to read message catalog: {path}") from exc
    except yaml.YAMLError as exc:
        raise MessageCatalogError(f"Failed to parse message catalog YAML: {path}") from exc

    if loaded is None:
        raise MessageCatalogError(f"Message catalog is empty: {path}")
    if not isinstance(loaded, dict):
        raise MessageCatalogError(
            f"Message catalog must contain a YAML mapping at the root: {path}"
        )

    raw_messages = _require_mapping(loaded, "messages", location="messages")
    normalized_messages: dict[str, dict[str, str]] = {}
    for section_name, required_keys in _REQUIRED_MESSAGE_KEYS.items():
        raw_section = _require_mapping(raw_messages, section_name, location=f"messages.{section_name}")
        normalized_section: dict[str, str] = {}
        for key_name in required_keys:
            normalized_section[key_name] = _require_text(
                raw_section,
                key_name,
                location=f"messages.{section_name}.{key_name}",
            )
        normalized_messages[section_name] = normalized_section

    return MessageCatalog(source_path=path, messages=normalized_messages)


def _resolve_messages_path(path: str | Path | None) -> Path:
    configured = path or os.getenv(_MESSAGES_PATH_ENV)
    candidate = Path(configured) if configured is not None else _DEFAULT_MESSAGES_PATH
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
        raise MessageCatalogError(f"Expected mapping at {location}.")
    return value


def _require_text(
    mapping: Mapping[str, Any],
    key: str,
    *,
    location: str,
) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise MessageCatalogError(f"Expected non-empty string at {location}.")
    normalized = value.strip()
    if not normalized:
        raise MessageCatalogError(f"Expected non-empty string at {location}.")
    return normalized


__all__ = [
    "MessageCatalog",
    "MessageCatalogError",
    "MessageTemplateService",
    "clear_message_catalog_cache",
    "default_message_template_service",
    "load_message_catalog",
]