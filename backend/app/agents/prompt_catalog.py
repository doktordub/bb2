"""YAML-backed prompt catalog and template helpers for agent/runtime prompts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os
from string import Formatter
from typing import Any

import yaml

from app.config.settings import BACKEND_ROOT
from app.contracts.errors import ConfigurationError

_DEFAULT_PROMPTS_PATH = BACKEND_ROOT / "config" / "prompts.yaml"
_PROMPTS_FROM_YAML_ENV = "PROMPTS_FROM_YAML_ENABLED"
_PROMPTS_PATH_ENV = "APP_PROMPTS_CONFIG_PATH"
_REQUIRED_PROMPT_PROFILES = frozenset(
    {
        "general_assistant_v1",
        "document_qa_v1",
        "tool_using_v1",
        "project_agent_v1",
        "memory_curator_v1",
        "reviewer_v1",
    }
)
_REQUIRED_SECTION_SPECS: dict[str, Mapping[str, str]] = {
    "tool_using": {
        "response_contract_with_tools": "text",
        "response_contract_with_tool_context": "text",
        "response_contract_no_tools": "text",
        "reasoning_rules": "text",
    },
    "reviewer": {
        "default_criteria": "list",
        "response_contract": "text",
        "review_rules": "text",
    },
    "memory_curator": {
        "response_contract": "text",
        "curation_rules": "text",
    },
    "document_qa": {
        "grounding_requirements": "list",
    },
    "project_agent": {
        "project_rules": "text",
    },
    "fallback_answer": {
        "llm_system_prompt": "text",
        "guidance": "text",
    },
}
_ALLOWED_TEMPLATE_FIELDS: dict[tuple[str, str], frozenset[str]] = {
    ("tool_using", "response_contract_with_tools"): frozenset(),
    ("tool_using", "response_contract_with_tool_context"): frozenset(),
    ("tool_using", "response_contract_no_tools"): frozenset(),
    ("tool_using", "reasoning_rules"): frozenset(),
    ("reviewer", "response_contract"): frozenset(),
    ("reviewer", "review_rules"): frozenset(),
    ("memory_curator", "response_contract"): frozenset(),
    ("memory_curator", "curation_rules"): frozenset(),
    ("project_agent", "project_rules"): frozenset(),
    ("fallback_answer", "llm_system_prompt"): frozenset(),
    ("fallback_answer", "guidance"): frozenset(),
}


class PromptCatalogError(ConfigurationError):
    """Prompt-catalog loading or validation failed."""


@dataclass(frozen=True, slots=True)
class PromptCatalog:
    """Validated prompt profiles and section templates loaded from YAML."""

    source_path: Path
    prompt_profiles: Mapping[str, str]
    sections: Mapping[str, Mapping[str, Any]]

    def resolve_system_prompt(self, prompt_profile: str | None) -> str | None:
        if prompt_profile is None:
            return None
        return _require_text(self.prompt_profiles, prompt_profile, location=f"prompt_profiles.{prompt_profile}")

    def get_text(self, section: str, key: str) -> str:
        section_mapping = _require_mapping(self.sections, section, location=f"sections.{section}")
        return _require_text(section_mapping, key, location=f"sections.{section}.{key}")

    def get_lines(self, section: str, key: str) -> tuple[str, ...]:
        section_mapping = _require_mapping(self.sections, section, location=f"sections.{section}")
        return _require_text_list(section_mapping, key, location=f"sections.{section}.{key}")

    def render_text(
        self,
        section: str,
        key: str,
        *,
        values: Mapping[str, object] | None = None,
    ) -> str:
        template = self.get_text(section, key)
        allowed_fields = _ALLOWED_TEMPLATE_FIELDS.get((section, key), frozenset())
        return _render_template(
            template,
            values=values or {},
            allowed_fields=allowed_fields,
            location=f"sections.{section}.{key}",
        )


class PromptTemplateService:
    """High-level prompt/template lookup service with cache and feature gating."""

    def __init__(self, catalog: PromptCatalog | None = None) -> None:
        self._catalog = catalog

    def prompts_from_yaml_enabled(self) -> bool:
        raw = os.getenv(_PROMPTS_FROM_YAML_ENV, "true")
        return raw.strip().lower() not in {"0", "false", "no", "off"}

    def catalog(self) -> PromptCatalog:
        if self._catalog is not None:
            return self._catalog
        return load_prompt_catalog()

    def resolve_system_prompt(
        self,
        prompt_profile: str | None,
        *,
        fallback_profiles: Mapping[str, str],
    ) -> str | None:
        if prompt_profile is None:
            return None
        if not self.prompts_from_yaml_enabled():
            return fallback_profiles.get(prompt_profile)
        return self.catalog().resolve_system_prompt(prompt_profile)

    def get_text(
        self,
        section: str,
        key: str,
        *,
        fallback: str,
        values: Mapping[str, object] | None = None,
    ) -> str:
        if not self.prompts_from_yaml_enabled():
            return _render_template(
                fallback,
                values=values or {},
                allowed_fields=_ALLOWED_TEMPLATE_FIELDS.get((section, key), frozenset()),
                location=f"fallback.{section}.{key}",
            )
        return self.catalog().render_text(section, key, values=values)

    def get_lines(
        self,
        section: str,
        key: str,
        *,
        fallback: Sequence[str],
    ) -> tuple[str, ...]:
        if not self.prompts_from_yaml_enabled():
            return tuple(fallback)
        return self.catalog().get_lines(section, key)


def default_prompt_template_service() -> PromptTemplateService:
    return _default_prompt_template_service()


def clear_prompt_catalog_cache() -> None:
    _load_prompt_catalog_cached.cache_clear()
    _default_prompt_template_service.cache_clear()


def load_prompt_catalog(path: str | Path | None = None) -> PromptCatalog:
    resolved_path = _resolve_prompts_path(path)
    return _load_prompt_catalog_cached(resolved_path)


def catalog_prompt_profiles() -> tuple[str, ...]:
    return tuple(load_prompt_catalog().prompt_profiles.keys())


@lru_cache(maxsize=1)
def _default_prompt_template_service() -> PromptTemplateService:
    return PromptTemplateService()


@lru_cache(maxsize=8)
def _load_prompt_catalog_cached(path: Path) -> PromptCatalog:
    if not path.exists():
        raise PromptCatalogError(f"Prompt catalog file does not exist: {path}")

    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded: Any = yaml.safe_load(handle)
    except OSError as exc:
        raise PromptCatalogError(f"Failed to read prompt catalog: {path}") from exc
    except yaml.YAMLError as exc:
        raise PromptCatalogError(f"Failed to parse prompt catalog YAML: {path}") from exc

    if loaded is None:
        raise PromptCatalogError(f"Prompt catalog is empty: {path}")
    if not isinstance(loaded, dict):
        raise PromptCatalogError(
            f"Prompt catalog must contain a YAML mapping at the root: {path}"
        )

    prompt_profiles_mapping = _require_mapping(
        loaded,
        "prompt_profiles",
        location="prompt_profiles",
    )
    sections_mapping = _require_mapping(loaded, "sections", location="sections")
    prompt_profiles = _normalize_text_mapping(
        prompt_profiles_mapping,
        location="prompt_profiles",
    )
    missing_profiles = sorted(_REQUIRED_PROMPT_PROFILES - set(prompt_profiles))
    if missing_profiles:
        raise PromptCatalogError(
            "Missing required prompt profile(s): " + ", ".join(missing_profiles)
        )

    normalized_sections: dict[str, dict[str, Any]] = {}
    for section_name, key_specs in _REQUIRED_SECTION_SPECS.items():
        raw_section = _require_mapping(
            sections_mapping,
            section_name,
            location=f"sections.{section_name}",
        )
        normalized_section: dict[str, Any] = {}
        for key_name, expected_kind in key_specs.items():
            if expected_kind == "text":
                normalized_section[key_name] = _require_text(
                    raw_section,
                    key_name,
                    location=f"sections.{section_name}.{key_name}",
                )
            elif expected_kind == "list":
                normalized_section[key_name] = list(
                    _require_text_list(
                        raw_section,
                        key_name,
                        location=f"sections.{section_name}.{key_name}",
                    )
                )
            else:
                raise PromptCatalogError(
                    f"Unsupported prompt catalog section type '{expected_kind}' for sections.{section_name}.{key_name}."
                )
        normalized_sections[section_name] = normalized_section

    _validate_template_placeholders(prompt_profiles, normalized_sections)
    return PromptCatalog(
        source_path=path,
        prompt_profiles=prompt_profiles,
        sections=normalized_sections,
    )


def _resolve_prompts_path(path: str | Path | None) -> Path:
    configured = path or os.getenv(_PROMPTS_PATH_ENV)
    candidate = Path(configured) if configured is not None else _DEFAULT_PROMPTS_PATH
    if not candidate.is_absolute():
        candidate = BACKEND_ROOT / candidate
    return candidate.resolve(strict=False)


def _normalize_text_mapping(raw_mapping: Mapping[str, Any], *, location: str) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in raw_mapping.items():
        if not isinstance(key, str) or not key.strip():
            raise PromptCatalogError(f"{location} keys must be non-empty strings.")
        if not isinstance(value, str) or not value.strip():
            raise PromptCatalogError(f"{location}.{key} must be a non-empty string.")
        normalized[key.strip()] = value.strip()
    return normalized


def _require_mapping(mapping: Mapping[str, Any], key: str, *, location: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        raise PromptCatalogError(f"{location} must be a mapping.")
    return value


def _require_text(mapping: Mapping[str, Any], key: str, *, location: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise PromptCatalogError(f"{location} must be a string.")
    normalized = value.strip()
    if not normalized:
        raise PromptCatalogError(f"{location} must not be blank.")
    return normalized


def _require_text_list(mapping: Mapping[str, Any], key: str, *, location: str) -> tuple[str, ...]:
    value = mapping.get(key)
    if not isinstance(value, list):
        raise PromptCatalogError(f"{location} must be a list of strings.")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise PromptCatalogError(f"{location} entries must be non-empty strings.")
        normalized.append(item.strip())
    if not normalized:
        raise PromptCatalogError(f"{location} must not be empty.")
    return tuple(normalized)


def _validate_template_placeholders(
    prompt_profiles: Mapping[str, str],
    sections: Mapping[str, Mapping[str, Any]],
) -> None:
    for prompt_profile, prompt_text in prompt_profiles.items():
        _validate_template_fields(
            prompt_text,
            location=f"prompt_profiles.{prompt_profile}",
            allowed_fields=frozenset(),
        )
    for section_name, key_values in sections.items():
        for key_name, value in key_values.items():
            if isinstance(value, str):
                _validate_template_fields(
                    value,
                    location=f"sections.{section_name}.{key_name}",
                    allowed_fields=_ALLOWED_TEMPLATE_FIELDS.get(
                        (section_name, key_name),
                        frozenset(),
                    ),
                )


def _validate_template_fields(
    template: str,
    *,
    location: str,
    allowed_fields: frozenset[str],
) -> None:
    if not allowed_fields:
        return
    formatter = Formatter()
    fields = {
        field_name
        for _, field_name, _, _ in formatter.parse(template)
        if field_name is not None and field_name != ""
    }
    unexpected_fields = sorted(fields - set(allowed_fields))
    if unexpected_fields:
        raise PromptCatalogError(
            f"{location} contains unsupported placeholder(s): {', '.join(unexpected_fields)}"
        )


def _render_template(
    template: str,
    *,
    values: Mapping[str, object],
    allowed_fields: frozenset[str],
    location: str,
) -> str:
    if not allowed_fields:
        return template
    _validate_template_fields(template, location=location, allowed_fields=allowed_fields)
    missing_fields = sorted(field for field in allowed_fields if field not in values)
    if missing_fields:
        raise PromptCatalogError(
            f"{location} requires placeholder value(s): {', '.join(missing_fields)}"
        )
    safe_values = {key: values[key] for key in allowed_fields}
    return template.format(**safe_values)


__all__ = [
    "PromptCatalog",
    "PromptCatalogError",
    "PromptTemplateService",
    "catalog_prompt_profiles",
    "clear_prompt_catalog_cache",
    "default_prompt_template_service",
    "load_prompt_catalog",
]