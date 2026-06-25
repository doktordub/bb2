"""Immutable validated configuration view."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from app.config.redaction import redact_config
from app.contracts.config import ConfigurationView
from app.contracts.errors import ConfigurationError
from app.observability.redaction import Redactor
from app.persistence.settings import get_persistence_settings

if TYPE_CHECKING:
    from app.persistence.settings import PersistenceSettings


@dataclass(frozen=True, slots=True)
class ObservabilitySettings:
    """Typed observability settings resolved from validated configuration."""

    log_level: str
    structured_logging: bool
    trace_enabled: bool
    trace_payloads_enabled: bool
    trace_store_required: bool
    redact_secrets: bool
    include_stack_traces_in_logs: bool
    include_stack_traces_in_traces: bool
    max_trace_payload_chars: int
    slow_request_ms: int
    slow_llm_call_ms: int
    slow_tool_call_ms: int
    metrics_enabled: bool


@dataclass(frozen=True, slots=True)
class HealthSettings:
    """Typed health settings resolved from validated configuration."""

    expose_config_summary: bool
    expose_provider_names: bool
    expose_secret_values: bool
    include_component_details: bool


class ValidatedConfigurationView:
    """Read-only runtime access to validated configuration values."""

    def __init__(self, values: Mapping[str, Any]) -> None:
        self._values = cast(Mapping[str, Any], _freeze(dict(values)))

    def get(self, path: str, default: Any = None) -> Any:
        if path == "":
            return self._values

        current: Any = self._values
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                return default
            current = current[part]
        return current

    def require(self, path: str) -> Any:
        value = self.get(path, None)
        if value is None:
            raise ConfigurationError(f"Missing required config path: {path}")
        return value

    def section(self, path: str) -> dict[str, Any]:
        value = self.require(path)
        if not isinstance(value, Mapping):
            raise ConfigurationError(f"Config path is not a section: {path}")
        return cast(dict[str, Any], _unfreeze(value))

    def observability_settings(self) -> ObservabilitySettings:
        return get_observability_settings(self)

    def health_settings(self) -> HealthSettings:
        return get_health_settings(self)

    def persistence_settings(self) -> PersistenceSettings:
        return get_persistence_settings(self)

    def as_redacted_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], redact_config(_unfreeze(self._values)))


def get_observability_settings(config: ConfigurationView) -> ObservabilitySettings:
    """Resolve typed observability settings from validated configuration."""

    return ObservabilitySettings(
        log_level=_read_str(config, "observability.log_level", "INFO"),
        structured_logging=_read_bool(config, "observability.structured_logging", True),
        trace_enabled=_read_bool(config, "observability.trace_enabled", True),
        trace_payloads_enabled=_read_bool(config, "observability.trace_payloads_enabled", True),
        trace_store_required=_read_bool(config, "observability.trace_store_required", True),
        redact_secrets=_read_bool(config, "observability.redact_secrets", True),
        include_stack_traces_in_logs=_read_bool(
            config,
            "observability.include_stack_traces_in_logs",
            False,
        ),
        include_stack_traces_in_traces=_read_bool(
            config,
            "observability.include_stack_traces_in_traces",
            False,
        ),
        max_trace_payload_chars=_read_int(
            config,
            "observability.max_trace_payload_chars",
            8000,
        ),
        slow_request_ms=_read_int(config, "observability.slow_request_ms", 5000),
        slow_llm_call_ms=_read_int(config, "observability.slow_llm_call_ms", 30000),
        slow_tool_call_ms=_read_int(config, "observability.slow_tool_call_ms", 10000),
        metrics_enabled=_read_bool(config, "observability.metrics_enabled", True),
    )


def get_health_settings(config: ConfigurationView) -> HealthSettings:
    """Resolve typed health settings from validated configuration."""

    return HealthSettings(
        expose_config_summary=_read_bool(config, "health.expose_config_summary", True),
        expose_provider_names=_read_bool(config, "health.expose_provider_names", True),
        expose_secret_values=_read_bool(config, "health.expose_secret_values", False),
        include_component_details=_read_bool(config, "health.include_component_details", True),
    )


def build_runtime_redactor(config: ConfigurationView) -> Redactor:
    """Build the runtime redactor from validated observability settings."""

    observability = get_observability_settings(config)
    return Redactor(
        redact_secrets=observability.redact_secrets,
        max_chars=observability.max_trace_payload_chars,
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})

    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)

    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)

    return value


def _unfreeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _unfreeze(item) for key, item in value.items()}

    if isinstance(value, tuple):
        return [_unfreeze(item) for item in value]

    return value


def _read_bool(config: ConfigurationView, path: str, default: bool) -> bool:
    value = config.get(path, default)
    if not isinstance(value, bool):
        raise ConfigurationError(f"Invalid config value at {path}: expected bool.")
    return value


def _read_int(config: ConfigurationView, path: str, default: int) -> int:
    value = config.get(path, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigurationError(f"Invalid config value at {path}: expected int.")
    return value


def _read_str(config: ConfigurationView, path: str, default: str) -> str:
    value = config.get(path, default)
    if not isinstance(value, str):
        raise ConfigurationError(f"Invalid config value at {path}: expected str.")
    return value