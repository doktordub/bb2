"""Structured logging setup for MCP bootstrap and runtime execution."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.observability.context import get_trace_context
from app.observability.tracing import TraceRecorder
from app.schemas import ObservabilitySettings
from app.security.redaction import Redactor


LOGGER_NAME = "mcp"


class JsonLogFormatter(logging.Formatter):
    """JSON formatter for structured runtime logging."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        context = getattr(record, "context", None)
        event_payload = getattr(record, "payload", None)
        if context:
            payload["context"] = context
        if event_payload is not None:
            payload["payload"] = event_payload
        return json.dumps(payload, ensure_ascii=True, default=str)


class TextLogFormatter(logging.Formatter):
    """Text formatter for bootstrap and local logging."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        fragments: list[str] = []
        context = getattr(record, "context", None)
        event_payload = getattr(record, "payload", None)
        if context:
            fragments.append(f"context={json.dumps(context, ensure_ascii=True, default=str)}")
        if event_payload is not None:
            fragments.append(f"payload={json.dumps(event_payload, ensure_ascii=True, default=str)}")
        if not fragments:
            return message
        return f"{message} {' '.join(fragments)}"


@dataclass(frozen=True, slots=True)
class StructuredLogger:
    """Small logger wrapper that redacts payloads before emission."""

    logger: logging.Logger
    redactor: Redactor
    context: dict[str, Any] = field(default_factory=dict)

    def bind(self, **context: Any) -> "StructuredLogger":
        combined = dict(self.context)
        combined.update(context)
        return StructuredLogger(logger=self.logger, redactor=self.redactor, context=combined)

    def debug(self, event: str, *, payload: Any | None = None, **context: Any) -> None:
        self._log(logging.DEBUG, event, payload=payload, **context)

    def info(self, event: str, *, payload: Any | None = None, **context: Any) -> None:
        self._log(logging.INFO, event, payload=payload, **context)

    def warning(self, event: str, *, payload: Any | None = None, **context: Any) -> None:
        self._log(logging.WARNING, event, payload=payload, **context)

    def error(self, event: str, *, payload: Any | None = None, **context: Any) -> None:
        self._log(logging.ERROR, event, payload=payload, **context)

    def _log(self, level: int, event: str, *, payload: Any | None = None, **context: Any) -> None:
        merged_context = dict(self.context)
        merged_context.update(context)
        trace_context = get_trace_context()
        if trace_context is not None:
            merged_context.setdefault("trace_id", trace_context.trace_id)
            if trace_context.request_id is not None:
                merged_context.setdefault("request_id", trace_context.request_id)
            if trace_context.caller_service is not None:
                merged_context.setdefault("caller_service", trace_context.caller_service)
            if trace_context.server_name is not None:
                merged_context.setdefault("server_name", trace_context.server_name)
            if trace_context.tool_name is not None:
                merged_context.setdefault("tool_name", trace_context.tool_name)
            if trace_context.capability_name is not None:
                merged_context.setdefault("capability_name", trace_context.capability_name)
        extras: dict[str, Any] = {}
        if merged_context:
            extras["context"] = self.redactor.sanitize(merged_context)
        if payload is not None:
            extras["payload"] = self.redactor.sanitize(payload)
        self.logger.log(level, event, extra=extras)


def emit_observability_event(
    logger: StructuredLogger,
    tracer: TraceRecorder | None,
    event_name: str,
    *,
    payload: Any | None = None,
    level: str = "info",
) -> None:
    """Write a safe observability event to logs and the local trace recorder."""

    log_method = getattr(logger, level, None)
    if callable(log_method):
        log_method(event_name, payload=payload)
    else:
        logger.info(event_name, payload=payload)

    if tracer is not None:
        tracer.record_event(event_name, payload)


def create_bootstrap_logger(redactor: Redactor | None = None) -> StructuredLogger:
    return _build_logger(level="INFO", json_logs=False, redactor=redactor or Redactor())


def configure_runtime_logger(
    settings: ObservabilitySettings,
    redactor: Redactor,
) -> StructuredLogger:
    return _build_logger(
        level=settings.log_level,
        json_logs=settings.json_logs,
        redactor=redactor,
    )


def _build_logger(level: str, json_logs: bool, redactor: Redactor) -> StructuredLogger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    handler = logging.StreamHandler()
    if json_logs:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(TextLogFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    logger.addHandler(handler)
    return StructuredLogger(logger=logger, redactor=redactor)