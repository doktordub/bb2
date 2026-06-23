import json
import logging
from pathlib import Path

from app.config.loader import load_validated_config
from app.config.settings import load_settings
from app.config.view import ValidatedConfigurationView
from app.observability.context import TraceContext, reset_trace_context, set_trace_context
from app.observability.logging import (
    FoundationContextFilter,
    JsonLogFormatter,
    ReadableLogFormatter,
    configure_logging,
    configure_logging_from_config,
)


FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "config"


def test_structured_logs_include_trace_context() -> None:
    record = logging.LogRecord(
        name="tests.observability",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="structured log",
        args=(),
        exc_info=None,
    )
    token = set_trace_context(
        TraceContext(
            trace_id="trace_0123456789abcdef0123456789abcdef",
            session_id="session-1",
            user_id="synthetic-user",
            usecase="default_chat",
            component="api.health",
        )
    )

    try:
        assert FoundationContextFilter(
            app_name="backend",
            app_version="0.1.0",
            app_env="test",
        ).filter(record)
    finally:
        reset_trace_context(token)

    payload = json.loads(JsonLogFormatter(include_stack_traces=False).format(record))

    assert payload["trace_id"] == "trace_0123456789abcdef0123456789abcdef"
    assert payload["session_id"] == "session-1"
    assert payload["component"] == "api.health"
    assert payload["usecase"] == "default_chat"
    assert payload["user_id_hash"] != "synthetic-user"


def test_logging_reconfiguration_uses_validated_observability_settings() -> None:
    logger = logging.Logger("tests.logging.reconfigure")
    logger.propagate = False
    settings = load_settings(env_file=None)

    configure_logging(settings, logger=logger)
    assert isinstance(logger.handlers[0].formatter, JsonLogFormatter)

    config = ValidatedConfigurationView(
        {
            "observability": {
                "log_level": "WARNING",
                "structured_logging": False,
                "trace_enabled": True,
                "trace_payloads_enabled": True,
                "trace_store_required": True,
                "redact_secrets": True,
                "include_stack_traces_in_logs": False,
                "include_stack_traces_in_traces": False,
                "max_trace_payload_chars": 4000,
                "slow_request_ms": 1000,
                "slow_llm_call_ms": 1000,
                "slow_tool_call_ms": 1000,
                "metrics_enabled": True,
            },
            "health": {
                "expose_config_summary": True,
                "expose_provider_names": True,
                "expose_secret_values": False,
                "include_component_details": True,
            },
        }
    )

    configure_logging_from_config(settings, config, logger=logger)

    assert logger.level == logging.WARNING
    assert isinstance(logger.handlers[0].formatter, ReadableLogFormatter)


def test_logging_reconfiguration_uses_unstructured_logging_override_fixture() -> None:
    logger = logging.Logger("tests.logging.fixture")
    logger.propagate = False
    settings = load_settings(env_file=None)
    parsed = load_validated_config(
        FIXTURES_DIR / "valid_minimal.yaml",
        override_path=FIXTURES_DIR / "observability_unstructured_logging.yaml",
        env={},
    )
    config = ValidatedConfigurationView(parsed.model_dump(mode="python"))

    configure_logging(settings, logger=logger)
    configure_logging_from_config(settings, config, logger=logger)

    assert logger.level == logging.INFO
    assert isinstance(logger.handlers[0].formatter, ReadableLogFormatter)