from pathlib import Path

import pytest

from app.config.loader import load_raw_config
from app.config.settings import BACKEND_ROOT, load_settings


SETTINGS_ENV_VARS = [
    "APP_ENV",
    "APP_DEBUG",
    "APP_USECASE",
    "APP_CONFIG_PATH",
    "APP_CONFIG_OVERRIDE_PATH",
    "APP_DATA_DIR",
    "APP_LOG_DIR",
    "APP_RUNTIME_DIR",
    "APP_CONFIG_STRICT",
    "APP_PUBLIC_BASE_URL",
    "APP_GRACEFUL_SHUTDOWN_SECONDS",
    "BACKEND_HOST",
    "BACKEND_PORT",
    "BACKEND_RELOAD",
    "APP_HOST",
    "APP_PORT",
    "APP_RELOAD",
    "LOG_LEVEL",
    "LOG_JSON",
    "LOG_FORMAT",
    "METRICS_ENABLED",
    "METRICS_BIND_HOST",
    "METRICS_PORT",
    "MCP_MAIN_URL",
    "LLM_LOCAL_QWEN_BASE_URL",
    "LLM_LOCAL_QWEN_API_KEY",
    "LOCAL_LLM_BASE_URL",
    "LOCAL_LLM_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "MEMORY_STORE_CONFIG",
    "MEMORY_STORE_CONFIG_PATH",
    "SQLITE_WORKFLOW_STATE_URL",
    "SQLITE_TRACE_URL",
]


def clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_env(monkeypatch)

    settings = load_settings(env_file=None)

    assert settings.app_name == "pluggable-agentic-ai-backend"
    assert settings.app_env == "local"
    assert settings.debug is False
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.app_config_path == "config/app.yaml"
    assert settings.app_config_override_path == "config/app.local.yaml"
    assert settings.app_data_dir == "data"
    assert settings.app_log_dir == "logs"
    assert settings.app_runtime_dir == "runtime"
    assert settings.app_config_strict is False
    assert settings.app_graceful_shutdown_seconds == 20
    assert settings.metrics_enabled is True
    assert settings.metrics_bind_host == "127.0.0.1"
    assert settings.metrics_port == 9102
    assert settings.log_json is True
    assert settings.resolved_app_config_path == (BACKEND_ROOT / "config/app.yaml").resolve()
    assert settings.resolved_app_config_override_path == (
        BACKEND_ROOT / "config/app.local.yaml"
    ).resolve()
    assert settings.resolved_app_data_dir == (BACKEND_ROOT / "data").resolve()
    assert settings.resolved_app_log_dir == (BACKEND_ROOT / "logs").resolve()
    assert settings.resolved_app_runtime_dir == (BACKEND_ROOT / "runtime").resolve()


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_DEBUG", "true")
    monkeypatch.setenv("APP_USECASE", "customer_support")
    monkeypatch.setenv("APP_CONFIG_PATH", "config/test/base.yaml")
    monkeypatch.setenv("APP_CONFIG_OVERRIDE_PATH", "config/test/override.yaml")
    monkeypatch.setenv("APP_DATA_DIR", "var/data")
    monkeypatch.setenv("APP_LOG_DIR", "var/log")
    monkeypatch.setenv("APP_RUNTIME_DIR", "var/run")
    monkeypatch.setenv("APP_CONFIG_STRICT", "true")
    monkeypatch.setenv("BACKEND_HOST", "0.0.0.0")
    monkeypatch.setenv("BACKEND_PORT", "9000")
    monkeypatch.setenv("BACKEND_RELOAD", "true")
    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "http://localhost:9000")
    monkeypatch.setenv("APP_GRACEFUL_SHUTDOWN_SECONDS", "25")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LOG_JSON", "false")
    monkeypatch.setenv("METRICS_ENABLED", "false")
    monkeypatch.setenv("METRICS_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("METRICS_PORT", "9200")
    monkeypatch.setenv("MEMORY_STORE_CONFIG", "../config/memory_store.yaml")

    settings = load_settings(env_file=None)

    assert settings.app_env == "test"
    assert settings.debug is True
    assert settings.app_usecase == "customer_support"
    assert settings.app_config_path == "config/test/base.yaml"
    assert settings.app_config_override_path == "config/test/override.yaml"
    assert settings.app_data_dir == "var/data"
    assert settings.app_log_dir == "var/log"
    assert settings.app_runtime_dir == "var/run"
    assert settings.app_config_strict is True
    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert settings.reload is True
    assert settings.app_public_base_url == "http://localhost:9000"
    assert settings.app_graceful_shutdown_seconds == 25
    assert settings.log_level == "DEBUG"
    assert settings.log_json is False
    assert settings.metrics_enabled is False
    assert settings.metrics_bind_host == "0.0.0.0"
    assert settings.metrics_port == 9200
    assert settings.memory_store_config == "../config/memory_store.yaml"
    assert settings.resolved_app_config_path == (BACKEND_ROOT / "config/test/base.yaml").resolve()
    assert settings.resolved_app_config_override_path == (
        BACKEND_ROOT / "config/test/override.yaml"
    ).resolve()
    assert settings.resolved_app_data_dir == (BACKEND_ROOT / "var/data").resolve()
    assert settings.resolved_app_log_dir == (BACKEND_ROOT / "var/log").resolve()
    assert settings.resolved_app_runtime_dir == (BACKEND_ROOT / "var/run").resolve()


def test_settings_path_fields_fall_back_to_defaults_when_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.setenv("APP_CONFIG_PATH", "   ")
    monkeypatch.setenv("APP_CONFIG_OVERRIDE_PATH", "")
    monkeypatch.setenv("APP_DATA_DIR", "\t")
    monkeypatch.setenv("APP_LOG_DIR", " ")
    monkeypatch.setenv("APP_RUNTIME_DIR", "")

    settings = load_settings(env_file=None)

    assert settings.app_config_path == "config/app.yaml"
    assert settings.app_config_override_path == "config/app.local.yaml"
    assert settings.app_data_dir == "data"
    assert settings.app_log_dir == "logs"
    assert settings.app_runtime_dir == "runtime"


def test_settings_accepts_app_aliases_for_host_port_and_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.setenv("APP_HOST", "0.0.0.0")
    monkeypatch.setenv("APP_PORT", "9100")
    monkeypatch.setenv("APP_RELOAD", "true")
    monkeypatch.setenv("LOG_FORMAT", "text")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "local-key")
    monkeypatch.setenv("MEMORY_STORE_CONFIG_PATH", "config/memory_store.local.yaml")

    settings = load_settings(env_file=None)

    assert settings.host == "0.0.0.0"
    assert settings.port == 9100
    assert settings.reload is True
    assert settings.log_json is False
    assert settings.llm_local_qwen_base_url == "http://localhost:9999/v1"
    assert settings.llm_local_qwen_api_key == "local-key"
    assert settings.memory_store_config == "config/memory_store.local.yaml"


def test_missing_config_allowed_in_foundation_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_env(monkeypatch)

    config_data = load_raw_config(
        "../config/usecases/customer_support.yaml",
        active_usecase="customer_support",
        strict=False,
    )

    assert config_data["active_usecase"] == "customer_support"
    assert Path(config_data["source_path"]) == (
        BACKEND_ROOT / "../config/usecases/customer_support.yaml"
    ).resolve()
    assert config_data["config"] == {}


def test_load_raw_config_reads_yaml_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "usecase.yaml"
    config_path.write_text("feature:\n  enabled: true\n", encoding="utf-8")

    config_data = load_raw_config(str(config_path), active_usecase="demo")

    assert config_data["active_usecase"] == "demo"
    assert Path(config_data["source_path"]) == config_path.resolve()
    assert config_data["config"] == {"feature": {"enabled": True}}
