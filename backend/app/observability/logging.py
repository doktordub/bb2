"""Logging configuration for the backend foundation app."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.config.settings import Settings
from app.config.view import get_observability_settings
from app.contracts.config import ConfigurationView
from app.observability.context import get_trace_context

_FOUNDATION_HANDLER_ATTR = "_foundation_handler"
_OPTIONAL_LOG_FIELDS = (
    "component",
    "trace_id",
    "session_id",
    "user_id_hash",
    "usecase",
    "event_type",
    "operation",
    "duration_ms",
    "status",
    "error_type",
    "details",
)


class FoundationContextFilter(logging.Filter):
    """Populate foundation metadata on every log record."""

    def __init__(self, *, app_name: str, app_version: str, app_env: str) -> None:
        super().__init__()
        self._app_name = app_name
        self._app_version = app_version
        self._app_env = app_env

    def filter(self, record: logging.LogRecord) -> bool:
        context = get_trace_context()

        record.app_name = self._app_name
        record.app_version = self._app_version
        record.app_env = self._app_env

        if getattr(record, "trace_id", None) is None:
            record.trace_id = None if context is None else context.trace_id
        if getattr(record, "session_id", None) is None:
            record.session_id = None if context is None else context.session_id
        if getattr(record, "user_id_hash", None) is None:
            record.user_id_hash = None if context is None else stable_hash(context.user_id)
        if getattr(record, "usecase", None) is None:
            record.usecase = None if context is None else context.usecase
        if getattr(record, "component", None) is None:
            record.component = None if context is None else context.component
        if getattr(record, "event_type", None) is None:
            record.event_type = None
        if getattr(record, "operation", None) is None:
            record.operation = None
        if getattr(record, "duration_ms", None) is None:
            record.duration_ms = None
        if getattr(record, "status", None) is None:
            record.status = None
        if getattr(record, "error_type", None) is None:
            record.error_type = None
        if getattr(record, "details", None) is None:
            record.details = None
        return True


class JsonLogFormatter(logging.Formatter):
    """Serialize log records as compact JSON for structured logging."""

    def __init__(self, *, include_stack_traces: bool) -> None:
        super().__init__()
        self._include_stack_traces = include_stack_traces

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "app_name": getattr(record, "app_name", None),
            "app_version": getattr(record, "app_version", None),
            "app_env": getattr(record, "app_env", None),
        }

        payload.update(_optional_log_fields(record))

        if record.exc_info is not None:
            error_type = _error_type_from_record(record)
            if error_type is not None:
                payload.setdefault("error_type", error_type)
            if self._include_stack_traces:
                payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True, default=_json_default)


class ReadableLogFormatter(logging.Formatter):
    """Render local-development logs in a readable key-value style."""

    def __init__(self, *, include_stack_traces: bool) -> None:
        super().__init__()
        self._include_stack_traces = include_stack_traces

    def format(self, record: logging.LogRecord) -> str:
        parts = [
            datetime.now(UTC).isoformat(),
            record.levelname,
            record.name,
            f"[{getattr(record, 'app_name', None)}/{getattr(record, 'app_env', None)}]",
        ]

        fields = _optional_log_fields(record)
        error_type = _error_type_from_record(record)
        if error_type is not None:
            fields.setdefault("error_type", error_type)

        for key, value in fields.items():
            parts.append(f"{key}={_format_field_value(value)}")

        parts.append(record.getMessage())
        message = " ".join(parts)

        if record.exc_info is not None and self._include_stack_traces:
            return f"{message}\n{self.formatException(record.exc_info)}"

        return message


def configure_logging(settings: Settings, *, logger: logging.Logger | None = None) -> None:
    """Configure root logging without stacking duplicate handlers across app creation."""

    configure_logger(
        logger or logging.getLogger(),
        app_name=settings.app_name,
        app_version=settings.app_version,
        app_env=settings.app_env,
        log_level=settings.log_level,
        structured_logging=settings.log_json,
        include_stack_traces=False,
    )


def configure_logging_from_config(
    settings: Settings,
    config: ConfigurationView,
    *,
    logger: logging.Logger | None = None,
) -> None:
    """Reconfigure logging from validated observability settings after config load."""

    observability = get_observability_settings(config)
    configure_logger(
        logger or logging.getLogger(),
        app_name=settings.app_name,
        app_version=settings.app_version,
        app_env=settings.app_env,
        log_level=observability.log_level,
        structured_logging=observability.structured_logging,
        include_stack_traces=observability.include_stack_traces_in_logs,
    )


def configure_logger(
    logger: logging.Logger,
    *,
    app_name: str,
    app_version: str,
    app_env: str,
    log_level: str,
    structured_logging: bool,
    include_stack_traces: bool,
) -> None:
    """Apply observability logging configuration to the provided logger."""

    parsed_level = _parse_log_level(log_level)
    logger.setLevel(parsed_level)

    handler = _get_or_create_foundation_handler(logger)
    handler.setLevel(parsed_level)
    handler.setFormatter(
        JsonLogFormatter(include_stack_traces=include_stack_traces)
        if structured_logging
        else ReadableLogFormatter(include_stack_traces=include_stack_traces)
    )

    for existing_filter in list(handler.filters):
        handler.removeFilter(existing_filter)
    handler.addFilter(
        FoundationContextFilter(
            app_name=app_name,
            app_version=app_version,
            app_env=app_env,
        )
    )


def _get_or_create_foundation_handler(logger: logging.Logger) -> logging.Handler:
    for handler in logger.handlers:
        if bool(getattr(handler, _FOUNDATION_HANDLER_ATTR, False)):
            return handler

    handler = logging.StreamHandler()
    setattr(handler, _FOUNDATION_HANDLER_ATTR, True)
    logger.addHandler(handler)
    return handler


def _parse_log_level(raw_level: str) -> int:
    return logging._nameToLevel.get(raw_level.upper(), logging.INFO)


def stable_hash(value: str | None) -> str | None:
    """Return a short stable hash for potentially sensitive identifiers."""

    if not value:
        return None

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _optional_log_fields(record: logging.LogRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in _OPTIONAL_LOG_FIELDS:
        value = getattr(record, key, None)
        if value is not None:
            payload[key] = value
    return payload


def _error_type_from_record(record: logging.LogRecord) -> str | None:
    if record.exc_info is None or record.exc_info[0] is None:
        return None
    return record.exc_info[0].__name__


def _format_field_value(value: Any) -> str:
    if isinstance(value, dict | list | tuple):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True, default=_json_default)
    return str(value)


def _json_default(value: object) -> str:
    return str(value)