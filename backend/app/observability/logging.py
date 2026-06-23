"""Logging configuration for the backend foundation app."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.config.settings import Settings
from app.observability.middleware import get_trace_id

_FOUNDATION_HANDLER_ATTR = "_foundation_handler"


class FoundationContextFilter(logging.Filter):
    """Populate foundation metadata on every log record."""

    def __init__(self, *, settings: Settings) -> None:
        super().__init__()
        self._app_name = settings.app_name
        self._app_version = settings.app_version
        self._app_env = settings.app_env

    def filter(self, record: logging.LogRecord) -> bool:
        record.app_name = self._app_name
        record.app_version = self._app_version
        record.app_env = self._app_env
        record.trace_id = get_trace_id()
        return True


class JsonLogFormatter(logging.Formatter):
    """Serialize log records as compact JSON for structured logging."""

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
        trace_id = getattr(record, "trace_id", None)
        if trace_id is not None:
            payload["trace_id"] = trace_id

        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def configure_logging(settings: Settings) -> None:
    """Configure root logging without stacking duplicate handlers across app creation."""

    root_logger = logging.getLogger()
    log_level = _parse_log_level(settings.log_level)
    root_logger.setLevel(log_level)

    handler = _get_or_create_foundation_handler(root_logger)
    handler.setLevel(log_level)
    handler.setFormatter(_build_formatter(settings))

    for existing_filter in list(handler.filters):
        handler.removeFilter(existing_filter)
    handler.addFilter(FoundationContextFilter(settings=settings))


def _get_or_create_foundation_handler(root_logger: logging.Logger) -> logging.Handler:
    for handler in root_logger.handlers:
        if bool(getattr(handler, _FOUNDATION_HANDLER_ATTR, False)):
            return handler

    handler = logging.StreamHandler()
    setattr(handler, _FOUNDATION_HANDLER_ATTR, True)
    root_logger.addHandler(handler)
    return handler


def _build_formatter(settings: Settings) -> logging.Formatter:
    if settings.log_json:
        return JsonLogFormatter()

    return logging.Formatter(
        fmt=(
            "%(asctime)s %(levelname)s %(name)s "
            "[%(app_name)s/%(app_env)s] [trace_id=%(trace_id)s] %(message)s"
        )
    )


def _parse_log_level(raw_level: str) -> int:
    return logging._nameToLevel.get(raw_level.upper(), logging.INFO)