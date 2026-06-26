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


@dataclass(frozen=True, slots=True)
class CorsSettings:
    """Typed API CORS settings resolved from validated configuration."""

    enabled: bool
    allow_origins: tuple[str, ...]
    allow_credentials: bool
    allow_methods: tuple[str, ...]
    allow_headers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApiRequestLimitSettings:
    """Typed API request limits resolved from validated configuration."""

    max_body_bytes: int
    max_message_chars: int
    max_metadata_bytes: int
    request_timeout_seconds: int
    stream_timeout_seconds: int


@dataclass(frozen=True, slots=True)
class ApiSessionSettings:
    """Typed API session settings resolved from validated configuration."""

    accept_client_session_id: bool
    create_session_when_missing: bool
    session_id_header: str


@dataclass(frozen=True, slots=True)
class ApiTracingSettings:
    """Typed API tracing settings resolved from validated configuration."""

    accept_client_trace_id: bool
    response_trace_header: str
    record_request_received: bool
    record_response_returned: bool
    record_validation_errors: bool


@dataclass(frozen=True, slots=True)
class ApiDebugRoutesSettings:
    """Typed API debug-route settings resolved from validated configuration."""

    enabled: bool
    require_localhost: bool
    max_trace_events: int
    max_search_results: int


@dataclass(frozen=True, slots=True)
class ApiSseSettings:
    """Typed API SSE settings resolved from validated configuration."""

    heartbeat_seconds: int
    send_trace_id_event: bool
    send_metadata_events: bool


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Typed API settings resolved from validated configuration."""

    enabled: bool
    base_path: str
    docs_enabled: bool
    openapi_enabled: bool
    cors: CorsSettings
    request_limits: ApiRequestLimitSettings
    sessions: ApiSessionSettings
    tracing: ApiTracingSettings
    debug_routes: ApiDebugRoutesSettings
    sse: ApiSseSettings


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

    def api_settings(self) -> ApiSettings:
        return get_api_settings(self)

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


def get_api_settings(config: ConfigurationView) -> ApiSettings:
    """Resolve typed API settings from validated configuration."""

    return ApiSettings(
        enabled=_read_bool(config, "api.enabled", True),
        base_path=_read_str(config, "api.base_path", ""),
        docs_enabled=_read_bool(config, "api.docs_enabled", True),
        openapi_enabled=_read_bool(config, "api.openapi_enabled", True),
        cors=CorsSettings(
            enabled=_read_bool(config, "api.cors.enabled", False),
            allow_origins=_read_str_tuple(config, "api.cors.allow_origins", ()),
            allow_credentials=_read_bool(config, "api.cors.allow_credentials", True),
            allow_methods=_read_str_tuple(
                config,
                "api.cors.allow_methods",
                ("GET", "POST", "OPTIONS"),
            ),
            allow_headers=_read_str_tuple(
                config,
                "api.cors.allow_headers",
                ("Authorization", "Content-Type", "X-Request-Id", "X-Trace-Id"),
            ),
        ),
        request_limits=ApiRequestLimitSettings(
            max_body_bytes=_read_int(config, "api.request_limits.max_body_bytes", 1048576),
            max_message_chars=_read_int(
                config,
                "api.request_limits.max_message_chars",
                20000,
            ),
            max_metadata_bytes=_read_int(
                config,
                "api.request_limits.max_metadata_bytes",
                65536,
            ),
            request_timeout_seconds=_read_int(
                config,
                "api.request_limits.request_timeout_seconds",
                120,
            ),
            stream_timeout_seconds=_read_int(
                config,
                "api.request_limits.stream_timeout_seconds",
                300,
            ),
        ),
        sessions=ApiSessionSettings(
            accept_client_session_id=_read_bool(
                config,
                "api.sessions.accept_client_session_id",
                True,
            ),
            create_session_when_missing=_read_bool(
                config,
                "api.sessions.create_session_when_missing",
                True,
            ),
            session_id_header=_read_str(
                config,
                "api.sessions.session_id_header",
                "X-Session-Id",
            ),
        ),
        tracing=ApiTracingSettings(
            accept_client_trace_id=_read_bool(
                config,
                "api.tracing.accept_client_trace_id",
                True,
            ),
            response_trace_header=_read_str(
                config,
                "api.tracing.response_trace_header",
                "X-Trace-Id",
            ),
            record_request_received=_read_bool(
                config,
                "api.tracing.record_request_received",
                True,
            ),
            record_response_returned=_read_bool(
                config,
                "api.tracing.record_response_returned",
                True,
            ),
            record_validation_errors=_read_bool(
                config,
                "api.tracing.record_validation_errors",
                True,
            ),
        ),
        debug_routes=ApiDebugRoutesSettings(
            enabled=_read_bool(config, "api.debug_routes.enabled", False),
            require_localhost=_read_bool(
                config,
                "api.debug_routes.require_localhost",
                True,
            ),
            max_trace_events=_read_int(
                config,
                "api.debug_routes.max_trace_events",
                500,
            ),
            max_search_results=_read_int(
                config,
                "api.debug_routes.max_search_results",
                50,
            ),
        ),
        sse=ApiSseSettings(
            heartbeat_seconds=_read_int(config, "api.sse.heartbeat_seconds", 15),
            send_trace_id_event=_read_bool(
                config,
                "api.sse.send_trace_id_event",
                True,
            ),
            send_metadata_events=_read_bool(
                config,
                "api.sse.send_metadata_events",
                True,
            ),
        ),
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


def _read_str_tuple(
    config: ConfigurationView,
    path: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    value = config.get(path, default)
    if isinstance(value, tuple):
        items = value
    elif isinstance(value, list):
        items = tuple(value)
    else:
        raise ConfigurationError(f"Invalid config value at {path}: expected list[str].")

    if not all(isinstance(item, str) for item in items):
        raise ConfigurationError(f"Invalid config value at {path}: expected list[str].")

    return cast(tuple[str, ...], items)