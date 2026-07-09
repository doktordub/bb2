"""Pydantic models for MCP tool manifests."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.tools_base.models import CapabilityDescriptor, RiskLevel, ToolDescriptor, ToolStatus


TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _validate_json_schema_shape(value: object, *, field_name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be 'auto' or a JSON-schema-shaped object.")


class StrictManifestModel(BaseModel):
    """Base model for MCP manifest validation."""

    model_config = ConfigDict(extra="forbid")


class ManifestCapability(StrictManifestModel):
    name: str
    type: str
    description: str
    risk_level: RiskLevel

    @field_validator("name", "type", "description")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Manifest capability fields must not be empty.")
        return normalized


class ManifestTool(StrictManifestModel):
    name: str
    function: str
    capability: str
    description: str
    risk_level: RiskLevel
    input_schema: Literal["auto"] | dict[str, Any]
    output_schema: str | dict[str, Any] | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)
    max_result_bytes: int | None = Field(default=None, ge=1)
    tags: tuple[str, ...] = ()

    @field_validator("name", "function", "capability", "description")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Manifest tool fields must not be empty.")
        return normalized

    @field_validator("input_schema")
    @classmethod
    def validate_input_schema(cls, value: Literal["auto"] | dict[str, Any]) -> Literal["auto"] | dict[str, Any]:
        if value != "auto":
            _validate_json_schema_shape(value, field_name="tools[].input_schema")
        return value

    @field_validator("output_schema")
    @classmethod
    def validate_output_schema(cls, value: str | dict[str, Any] | None) -> str | dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                raise ValueError("tools[].output_schema must not be empty when provided.")
            return normalized
        _validate_json_schema_shape(value, field_name="tools[].output_schema")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not tag.strip() for tag in value):
            raise ValueError("tools[].tags must not contain empty values.")
        return value


class ToolConfigSchema(BaseModel):
    """Minimal JSON schema model for tool-local configuration."""

    model_config = ConfigDict(extra="allow")

    type: str | None = None
    required: list[str] = Field(default_factory=list)
    properties: dict[str, dict[str, Any]] = Field(default_factory=dict)
    additionalProperties: bool | dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_schema(self) -> "ToolConfigSchema":
        if self.type not in (None, "object"):
            raise ValueError("config_schema.type must be 'object' when provided.")
        if any(not key.strip() for key in self.required):
            raise ValueError("config_schema.required must not contain empty keys.")
        if any(not key.strip() for key in self.properties):
            raise ValueError("config_schema.properties keys must not be empty.")
        missing = [key for key in self.required if key not in self.properties]
        if missing:
            raise ValueError(
                "config_schema.required must only reference declared properties: "
                + ", ".join(sorted(missing))
            )
        return self


class ToolManifest(StrictManifestModel):
    name: str
    package: str
    version: str
    status: ToolStatus
    owner: str
    required: bool
    description: str
    capabilities: list[ManifestCapability]
    tools: list[ManifestTool]
    config_schema: ToolConfigSchema = Field(default_factory=ToolConfigSchema)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not TOOL_NAME_PATTERN.fullmatch(normalized):
            raise ValueError(
                "Manifest name must be folder-safe snake_case starting with a letter."
            )
        return normalized

    @field_validator("package", "version", "owner", "description")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Manifest fields must not be empty.")
        return normalized

    @model_validator(mode="after")
    def validate_manifest(self) -> "ToolManifest":
        expected_package = f"mcp.tools.{self.name}"
        if self.package != expected_package:
            raise ValueError(f"Manifest package must be {expected_package!r}.")

        capability_names = [capability.name for capability in self.capabilities]
        if len(capability_names) != len(set(capability_names)):
            raise ValueError("Manifest capability names must be unique.")

        tool_names = [tool.name for tool in self.tools]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError("Manifest tool names must be unique.")

        declared_capabilities = set(capability_names)
        missing_capabilities = sorted(
            {tool.capability for tool in self.tools if tool.capability not in declared_capabilities}
        )
        if missing_capabilities:
            raise ValueError(
                "Manifest tools reference undeclared capabilities: "
                + ", ".join(missing_capabilities)
            )

        return self

    def capability_descriptors(self) -> list[CapabilityDescriptor]:
        return [
            CapabilityDescriptor(
                name=capability.name,
                type=capability.type,
                description=capability.description,
                risk_level=capability.risk_level,
            )
            for capability in self.capabilities
        ]

    def tool_descriptors(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name=tool.name,
                description=tool.description,
                capability=tool.capability,
                risk_level=tool.risk_level,
                input_schema=tool.input_schema,
                output_schema=tool.output_schema,
                timeout_seconds=tool.timeout_seconds,
                max_result_bytes=tool.max_result_bytes,
                tags=tool.tags,
            )
            for tool in self.tools
        ]