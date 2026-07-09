"""Dynamic discovery and registration for MCP tool plugins."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.util
from pathlib import Path
import re
import sys
from typing import Any

from fastmcp import FastMCP

from app.config import resolve_env_placeholders
from app.context import ServiceContainer
from app.errors import (
    MCPConfigurationError,
    MCPToolConfigurationError,
    MCPToolManifestError,
    MCPToolPluginError,
)
from app.observability.events import (
    MCP_TOOL_CONFIG_LOADED,
    MCP_TOOL_DISCOVERY_STARTED,
    MCP_TOOL_MANIFEST_LOADED,
    MCP_TOOL_REGISTERED,
    MCP_TOOL_REGISTRATION_FAILED,
)
from app.observability.logging import emit_observability_event
from app.registry import ToolRegistry
from app.schemas import AppSettings, ToolEnablementSettings
from app.tools_base.manifest import ToolManifest
from app.tools_base.plugin import PluginFactory
from app.tools_base.validation import (
    load_manifest,
    load_tool_config,
    validate_plugin_instance,
    validate_tool_config,
)


PLUGIN_MODULE_SUFFIX = ".plugin"
DEFAULT_TOOL_CONFIG_FILE = "config.yaml"
_SANITIZE_MODULE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_]+")


@dataclass(slots=True)
class ToolLoader:
    config_path: Path
    settings: AppSettings
    services: ServiceContainer

    def load_tools(self, server: FastMCP, registry: ToolRegistry) -> ToolRegistry:
        tools_dir = self.resolve_tools_dir()
        if not tools_dir.is_dir():
            raise MCPConfigurationError(f"Configured tools directory not found: {tools_dir}")

        emit_observability_event(
            self.services.logger,
            self.services.tracer,
            MCP_TOOL_DISCOVERY_STARTED,
            payload={
                "server_name": self.settings.server.name,
                "tools_directory": str(tools_dir),
            },
        )

        for tool_dir in self._iter_tool_dirs(tools_dir):
            self._load_tool_dir(tool_dir, server, registry)

        return registry

    def resolve_tools_dir(self) -> Path:
        configured_path = Path(self.settings.runtime.tools_dir)
        if configured_path.is_absolute():
            return configured_path

        mcp_root = Path(__file__).resolve().parents[1]
        repo_root = mcp_root.parent
        candidates = [
            repo_root / configured_path,
            mcp_root / configured_path,
            Path.cwd() / configured_path,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()

        return candidates[0].resolve()

    @staticmethod
    def _iter_tool_dirs(tools_dir: Path) -> list[Path]:
        return sorted(
            [
                path
                for path in tools_dir.iterdir()
                if path.is_dir() and not path.name.startswith("_")
            ],
            key=lambda path: path.name,
        )

    def _load_tool_dir(self, tool_dir: Path, server: FastMCP, registry: ToolRegistry) -> None:
        tool_name = tool_dir.name
        tool_settings = self.settings.tools.get(tool_name)
        enabled_hint = self._resolve_enabled(tool_settings)
        required_hint = self._resolve_required(tool_settings, manifest_required=False)
        manifest_path = tool_dir / "manifest.yaml"

        if not manifest_path.is_file():
            if self.settings.policy.require_tool_manifest and enabled_hint:
                self._handle_load_error(
                    tool_name=tool_name,
                    manifest=None,
                    required=required_hint,
                    error=MCPToolConfigurationError(
                        f"Enabled tool {tool_name!r} is missing manifest.yaml."
                    ),
                    registry=registry,
                )
            return

        try:
            manifest = load_manifest(manifest_path)
        except Exception as error:
            if enabled_hint:
                self._handle_load_error(
                    tool_name=tool_name,
                    manifest=None,
                    required=required_hint,
                    error=error,
                    registry=registry,
                )
            else:
                self.services.logger.warning(
                    "mcp.tool.manifest.ignored",
                    payload={
                        "tool_name": tool_name,
                        "error_type": error.__class__.__name__,
                        "message": str(error),
                    },
                )
            return

        emit_observability_event(
            self.services.logger,
            self.services.tracer,
            MCP_TOOL_MANIFEST_LOADED,
            payload={
                "tool_name": manifest.name,
                "version": manifest.version,
                "required": manifest.required,
                "capability_count": len(manifest.capabilities),
            },
        )

        resolved_manifest = manifest.model_copy(
            update={"required": self._resolve_required(tool_settings, manifest.required)}
        )

        if not self._resolve_enabled(tool_settings):
            registry.register_disabled(resolved_manifest)
            return

        try:
            registry.assert_can_register(resolved_manifest)
            merged_config = self._merge_tool_config(resolved_manifest, tool_dir, tool_settings)
            emit_observability_event(
                self.services.logger,
                self.services.tracer,
                MCP_TOOL_CONFIG_LOADED,
                payload={
                    "tool_name": resolved_manifest.name,
                    "config_keys": sorted(merged_config),
                },
            )
            plugin_factory = self._load_plugin_factory(resolved_manifest, tool_dir)
            plugin = plugin_factory(
                self.services.build_tool_runtime_context(
                    tool_name=resolved_manifest.name,
                    tool_config=merged_config,
                )
            )
            validate_plugin_instance(plugin, resolved_manifest)
            plugin.register(server)
            registry.register_plugin(plugin, resolved_manifest, merged_config)
            emit_observability_event(
                self.services.logger,
                self.services.tracer,
                MCP_TOOL_REGISTERED,
                payload={
                    "tool_name": resolved_manifest.name,
                    "version": resolved_manifest.version,
                    "capability_count": len(resolved_manifest.capabilities),
                    "fastmcp_tool_names": [
                        descriptor.name for descriptor in resolved_manifest.tool_descriptors()
                    ],
                    "status": "loaded",
                },
            )
        except Exception as error:
            self._handle_load_error(
                tool_name=tool_name,
                manifest=resolved_manifest,
                required=resolved_manifest.required,
                error=error,
                registry=registry,
            )

    def _merge_tool_config(
        self,
        manifest: ToolManifest,
        tool_dir: Path,
        tool_settings: ToolEnablementSettings | None,
    ) -> dict[str, Any]:
        merged_config: dict[str, Any] = self.settings.defaults.model_dump(mode="python")
        if tool_settings is not None:
            merged_config.update(tool_settings.runtime_config())

        local_config = self._load_local_config(tool_dir, tool_settings)
        merged_config.update(local_config)
        resolved_config = resolve_env_placeholders(merged_config)
        if not isinstance(resolved_config, dict):
            raise MCPToolConfigurationError("Resolved tool config must remain a mapping.")
        merged_config = {str(key): value for key, value in resolved_config.items()}

        if self.settings.policy.require_tool_config_validation:
            validation_config = {
                key: merged_config[key]
                for key in manifest.config_schema.properties
                if key in merged_config
            }
            validate_tool_config(manifest, validation_config)

        return merged_config

    def _load_local_config(
        self,
        tool_dir: Path,
        tool_settings: ToolEnablementSettings | None,
    ) -> dict[str, Any]:
        config_file_name = DEFAULT_TOOL_CONFIG_FILE
        explicit_config_file = False
        if tool_settings is not None and tool_settings.config_file:
            config_file_name = tool_settings.config_file
            explicit_config_file = True

        config_path = Path(config_file_name)
        if not config_path.is_absolute():
            config_path = tool_dir / config_path

        if not config_path.exists():
            if explicit_config_file:
                raise MCPToolConfigurationError(
                    f"Configured tool config file not found: {config_path}"
                )
            return {}

        resolved_config = resolve_env_placeholders(load_tool_config(config_path))
        if not isinstance(resolved_config, dict):
            raise MCPToolConfigurationError("Resolved tool config file must be a mapping.")
        return {str(key): value for key, value in resolved_config.items()}

    def _load_plugin_factory(self, manifest: ToolManifest, tool_dir: Path) -> PluginFactory:
        module_name = f"{manifest.package}{PLUGIN_MODULE_SUFFIX}"
        module = self._import_plugin_module(module_name, tool_dir / "plugin.py")
        plugin_factory = getattr(module, "create_plugin", None)
        if not callable(plugin_factory):
            raise MCPToolPluginError(
                f"Tool plugin {manifest.name!r} does not define callable create_plugin(context)."
            )
        return plugin_factory

    def _import_plugin_module(self, module_name: str, plugin_path: Path) -> Any:
        direct_import_error: ModuleNotFoundError | None = None
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            if not self._is_target_module_not_found(error, module_name):
                raise
            direct_import_error = error

        if module_name.startswith("mcp."):
            fallback_module_name = module_name.removeprefix("mcp.")
            try:
                return importlib.import_module(fallback_module_name)
            except ModuleNotFoundError as error:
                if not self._is_target_module_not_found(error, fallback_module_name):
                    raise

        if not plugin_path.is_file():
            raise MCPToolPluginError(f"Tool plugin file not found: {plugin_path}") from direct_import_error

        dynamic_module_name = self._build_dynamic_module_name(plugin_path)
        spec = importlib.util.spec_from_file_location(dynamic_module_name, plugin_path)
        if spec is None or spec.loader is None:
            raise MCPToolPluginError(f"Unable to load tool plugin module from {plugin_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[dynamic_module_name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _is_target_module_not_found(error: ModuleNotFoundError, module_name: str) -> bool:
        missing_name = error.name or ""
        return missing_name == module_name or module_name.startswith(f"{missing_name}.")

    @staticmethod
    def _build_dynamic_module_name(plugin_path: Path) -> str:
        sanitized_path = _SANITIZE_MODULE_NAME_PATTERN.sub("_", str(plugin_path.resolve()))
        return f"_mcp_dynamic_{sanitized_path}"

    def _handle_load_error(
        self,
        *,
        tool_name: str,
        manifest: ToolManifest | None,
        required: bool,
        error: Exception,
        registry: ToolRegistry,
    ) -> None:
        if manifest is not None and not isinstance(error, MCPToolPluginError):
            registry.register_failed(manifest, error, required)
        elif manifest is not None:
            registry.register_failed(manifest, error, required)
        else:
            registry.register_failed(tool_name, error, required)

        emit_observability_event(
            self.services.logger,
            self.services.tracer,
            MCP_TOOL_REGISTRATION_FAILED,
            payload={
                "tool_name": tool_name,
                "required": required,
                "error_code": error.__class__.__name__,
            },
            level="warning",
        )

        should_fail = (
            isinstance(error, (MCPToolConfigurationError, MCPToolManifestError))
            or (
                isinstance(error, MCPToolPluginError)
                and "Duplicate FastMCP tool name" in str(error)
            )
            or required
            or self.settings.runtime.fail_on_optional_tool_error
        )
        if should_fail:
            raise error

        self.services.logger.warning(
            "mcp.tool.load.degraded",
            payload={
                "tool_name": tool_name,
                "required": required,
                "error_type": error.__class__.__name__,
                "message": str(error),
            },
        )

    def _resolve_enabled(self, tool_settings: ToolEnablementSettings | None) -> bool:
        if tool_settings is None:
            return self.settings.policy.default_tool_enabled
        return tool_settings.enabled

    @staticmethod
    def _resolve_required(
        tool_settings: ToolEnablementSettings | None,
        manifest_required: bool,
    ) -> bool:
        if tool_settings is None:
            return manifest_required
        return tool_settings.required