from pathlib import Path

import pytest

from app.config import load_settings, redacted_settings_summary
from app.errors import MCPConfigurationError


def _write_config(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_load_settings_valid_config(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "app.yaml",
        """
server:
  name: main_mcp
  version: 1.0.0
  environment: test
  host: 127.0.0.1
  port: 9001
  path: /mcp
  transport: http
runtime:
  tools_dir: mcp/tools
  discovery_on_startup: true
  fail_on_required_tool_error: true
  fail_on_optional_tool_error: false
security:
  inbound_auth:
    enabled: false
    mode: none
  outbound_auth:
    default_mode: none
  tls:
    mode: terminate_upstream
    behind_proxy: true
  secrets:
    provider: env
    allow_tool_env_prefixes: [MCP_TOOL_, WEBSEARCH_]
policy:
  expose_health_tool: true
observability:
  log_level: INFO
  json_logs: true
  redact_secrets: true
  max_log_payload_chars: 2000
defaults:
  timeout_seconds: 30
  max_result_bytes: 262144
  max_argument_bytes: 65536
  max_results: 10
  rate_limit:
    enabled: true
    per_tool_per_minute: 60
tools:
  websearch:
    enabled: true
    required: true
    config_file: config.yaml
""",
    )

    settings = load_settings(config_path)

    assert settings.server.transport == "http"
    assert settings.defaults.rate_limit.per_tool_per_minute == 60
    assert settings.tools["websearch"].enabled is True


def test_load_settings_rejects_invalid_transport(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "app.yaml",
        """
server:
  name: main_mcp
  version: 1.0.0
  environment: test
  host: 127.0.0.1
  port: 9001
  path: /mcp
  transport: ftp
runtime:
  tools_dir: mcp/tools
  discovery_on_startup: true
  fail_on_required_tool_error: true
  fail_on_optional_tool_error: false
security:
  inbound_auth:
    enabled: false
    mode: none
  outbound_auth:
    default_mode: none
  tls:
    mode: terminate_upstream
    behind_proxy: true
  secrets:
    provider: env
    allow_tool_env_prefixes: [MCP_TOOL_]
policy:
  expose_health_tool: true
observability:
  log_level: INFO
  json_logs: true
  redact_secrets: true
  max_log_payload_chars: 2000
defaults:
  timeout_seconds: 30
  max_result_bytes: 262144
  max_argument_bytes: 65536
  max_results: 10
  rate_limit:
    enabled: true
    per_tool_per_minute: 60
""",
    )

    with pytest.raises(MCPConfigurationError):
        load_settings(config_path)


def test_redacted_settings_summary_is_safe(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "app.yaml",
        """
server:
  name: main_mcp
  version: 1.0.0
  environment: test
  host: 127.0.0.1
  port: 9001
  path: /mcp
  transport: http
runtime:
  tools_dir: mcp/tools
  discovery_on_startup: true
  fail_on_required_tool_error: true
  fail_on_optional_tool_error: false
security:
  inbound_auth:
    enabled: false
    mode: none
  outbound_auth:
    default_mode: none
  tls:
    mode: terminate_upstream
    behind_proxy: true
  secrets:
    provider: env
    allow_tool_env_prefixes: [WEBSEARCH_]
policy:
  expose_health_tool: true
observability:
  log_level: INFO
  json_logs: true
  redact_secrets: true
  max_log_payload_chars: 2000
defaults:
  timeout_seconds: 30
  max_result_bytes: 262144
  max_argument_bytes: 65536
  max_results: 10
  rate_limit:
    enabled: true
    per_tool_per_minute: 60
""",
    )

    summary = redacted_settings_summary(load_settings(config_path))

    assert summary["security"]["credential_provider"] == "env"
    assert "bearer_token_env" not in str(summary)


def test_load_settings_rejects_none_auth_outside_local_when_enabled(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "app.yaml",
        """
server:
  name: main_mcp
  version: 1.0.0
  environment: production
  host: 127.0.0.1
  port: 9001
  path: /mcp
  transport: http
runtime:
  tools_dir: mcp/tools
  discovery_on_startup: true
  fail_on_required_tool_error: true
  fail_on_optional_tool_error: false
security:
  inbound_auth:
    enabled: true
    mode: none
  outbound_auth:
    default_mode: none
  tls:
    mode: terminate_upstream
    behind_proxy: true
  secrets:
    provider: env
    allow_tool_env_prefixes: [MCP_TOOL_]
policy:
  expose_health_tool: true
observability:
  log_level: INFO
  json_logs: true
  redact_secrets: true
  max_log_payload_chars: 2000
defaults:
  timeout_seconds: 30
  max_result_bytes: 262144
  max_argument_bytes: 65536
  max_results: 10
  rate_limit:
    enabled: true
    per_tool_per_minute: 60
""",
    )

    with pytest.raises(MCPConfigurationError):
        load_settings(config_path)


def test_load_settings_rejects_terminate_here_without_certificates(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path / "app.yaml",
        """
server:
  name: main_mcp
  version: 1.0.0
  environment: local
  host: 127.0.0.1
  port: 9001
  path: /mcp
  transport: http
runtime:
  tools_dir: mcp/tools
  discovery_on_startup: true
  fail_on_required_tool_error: true
  fail_on_optional_tool_error: false
security:
  inbound_auth:
    enabled: false
    mode: none
  outbound_auth:
    default_mode: none
  tls:
    mode: terminate_here
    behind_proxy: false
  secrets:
    provider: env
    allow_tool_env_prefixes: [MCP_TOOL_]
policy:
  expose_health_tool: true
observability:
  log_level: INFO
  json_logs: true
  redact_secrets: true
  max_log_payload_chars: 2000
defaults:
  timeout_seconds: 30
  max_result_bytes: 262144
  max_argument_bytes: 65536
  max_results: 10
  rate_limit:
    enabled: true
    per_tool_per_minute: 60
""",
    )

    with pytest.raises(MCPConfigurationError):
        load_settings(config_path)