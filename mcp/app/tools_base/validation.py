"""Manifest, config, and plugin validation helpers for MCP tool plugins."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import inspect
from pathlib import Path
import re
from typing import Any

import yaml
from pydantic import ValidationError

from app.errors import MCPToolConfigurationError, MCPToolManifestError, MCPToolPluginError
from app.tools_base.manifest import ToolManifest
from app.tools_base.models import CapabilityDescriptor


def _load_yaml_mapping(path: Path, *, label: str, error_type: type[RuntimeError]) -> dict[str, Any]:
    if not path.is_file():
        raise error_type(f"{label} file not found: {path}")

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise error_type(f"Invalid YAML in {label} file: {path}") from exc

    if not isinstance(data, dict):
        raise error_type(f"{label} root must be a mapping: {path}")
    return data


def load_manifest(path: str | Path) -> ToolManifest:
    manifest_path = Path(path)
    raw_manifest = _load_yaml_mapping(
        manifest_path,
        label="tool manifest",
        error_type=MCPToolManifestError,
    )

    try:
        manifest = ToolManifest.model_validate(raw_manifest)
    except ValidationError as exc:
        raise MCPToolManifestError(f"Invalid tool manifest at {manifest_path}: {exc}") from exc

    folder_name = manifest_path.parent.name
    if manifest.name != folder_name:
        raise MCPToolManifestError(
            f"Manifest name {manifest.name!r} must match folder name {folder_name!r}."
        )

    return manifest


def load_tool_config(path: str | Path) -> dict[str, Any]:
    return _load_yaml_mapping(
        Path(path),
        label="tool config",
        error_type=MCPToolConfigurationError,
    )


def validate_tool_config(manifest: ToolManifest, config: Mapping[str, Any]) -> None:
    if not isinstance(config, Mapping):
        raise MCPToolConfigurationError("Tool config must be a mapping.")

    schema = manifest.config_schema
    missing_required = [key for key in schema.required if key not in config]
    if missing_required:
        raise MCPToolConfigurationError(
            "Tool config is missing required keys: " + ", ".join(sorted(missing_required))
        )

    if schema.additionalProperties is False:
        extra_keys = sorted(set(config) - set(schema.properties))
        if extra_keys:
            raise MCPToolConfigurationError(
                "Tool config contains unsupported keys: " + ", ".join(extra_keys)
            )

    for key, value in config.items():
        property_schema = schema.properties.get(key)
        if property_schema is None:
            continue
        _validate_schema_value(key=key, value=value, schema=property_schema)


def _validate_schema_value(*, key: str, value: Any, schema: Mapping[str, Any]) -> None:
    expected_type = schema.get("type")
    if expected_type == "string":
        if not isinstance(value, str):
            raise MCPToolConfigurationError(f"Tool config key {key!r} must be a string.")
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if min_length is not None and len(value) < int(min_length):
            raise MCPToolConfigurationError(
                f"Tool config key {key!r} must be at least {min_length} characters long."
            )
        if max_length is not None and len(value) > int(max_length):
            raise MCPToolConfigurationError(
                f"Tool config key {key!r} must be at most {max_length} characters long."
            )
        pattern = schema.get("pattern")
        if pattern is not None and re.fullmatch(str(pattern), value) is None:
            raise MCPToolConfigurationError(
                f"Tool config key {key!r} does not match the required pattern."
            )
    elif expected_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise MCPToolConfigurationError(f"Tool config key {key!r} must be an integer.")
    elif expected_type == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise MCPToolConfigurationError(f"Tool config key {key!r} must be numeric.")
    elif expected_type == "boolean":
        if not isinstance(value, bool):
            raise MCPToolConfigurationError(f"Tool config key {key!r} must be a boolean.")
    elif expected_type == "object":
        if not isinstance(value, Mapping):
            raise MCPToolConfigurationError(f"Tool config key {key!r} must be an object.")
    elif expected_type == "array":
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            raise MCPToolConfigurationError(f"Tool config key {key!r} must be an array.")
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if min_items is not None and len(value) < int(min_items):
            raise MCPToolConfigurationError(
                f"Tool config key {key!r} must contain at least {min_items} items."
            )
        if max_items is not None and len(value) > int(max_items):
            raise MCPToolConfigurationError(
                f"Tool config key {key!r} must contain at most {max_items} items."
            )

    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if minimum is not None and isinstance(value, int | float) and value < minimum:
        raise MCPToolConfigurationError(
            f"Tool config key {key!r} must be greater than or equal to {minimum}."
        )
    if maximum is not None and isinstance(value, int | float) and value > maximum:
        raise MCPToolConfigurationError(
            f"Tool config key {key!r} must be less than or equal to {maximum}."
        )

    allowed_values = schema.get("enum")
    if allowed_values is not None and value not in allowed_values:
        raise MCPToolConfigurationError(
            f"Tool config key {key!r} must be one of {allowed_values!r}."
        )


def validate_plugin_instance(plugin: Any, manifest: ToolManifest) -> None:
    missing_attributes = [
        attribute
        for attribute in ("name", "version", "capabilities", "register", "health")
        if not hasattr(plugin, attribute)
    ]
    if missing_attributes:
        raise MCPToolPluginError(
            "Plugin instance is missing required attributes: "
            + ", ".join(sorted(missing_attributes))
        )

    if plugin.name != manifest.name:
        raise MCPToolPluginError(
            f"Plugin name {plugin.name!r} does not match manifest name {manifest.name!r}."
        )
    if plugin.version != manifest.version:
        raise MCPToolPluginError(
            f"Plugin version {plugin.version!r} does not match manifest version {manifest.version!r}."
        )
    if not callable(plugin.register):
        raise MCPToolPluginError("Plugin register attribute must be callable.")
    if not callable(plugin.health) or not inspect.iscoroutinefunction(plugin.health):
        raise MCPToolPluginError("Plugin health attribute must be implemented as an async method.")

    capabilities = plugin.capabilities
    if not isinstance(capabilities, list):
        raise MCPToolPluginError("Plugin capabilities must be a list of CapabilityDescriptor values.")
    if any(not isinstance(capability, CapabilityDescriptor) for capability in capabilities):
        raise MCPToolPluginError(
            "Plugin capabilities must only contain CapabilityDescriptor values."
        )

    manifest_capabilities = {capability.name: capability for capability in manifest.capabilities}
    plugin_capabilities = {capability.name: capability for capability in capabilities}

    if set(plugin_capabilities) != set(manifest_capabilities):
        raise MCPToolPluginError(
            "Plugin capabilities do not match manifest capabilities."
        )

    for capability_name, declared in manifest_capabilities.items():
        actual = plugin_capabilities[capability_name]
        if actual.type != declared.type:
            raise MCPToolPluginError(
                f"Plugin capability {capability_name!r} type does not match the manifest."
            )
        if actual.description != declared.description:
            raise MCPToolPluginError(
                f"Plugin capability {capability_name!r} description does not match the manifest."
            )
        if actual.risk_level != declared.risk_level:
            raise MCPToolPluginError(
                f"Plugin capability {capability_name!r} risk level does not match the manifest."
            )