from pathlib import Path

import pytest

from app.config.loader import load_raw_config
from app.config.settings import BACKEND_ROOT, load_settings


SETTINGS_ENV_VARS = [
    "APP_ENV",
    "APP_DEBUG",
    "APP_USECASE",
    "APP_CONFIG_PATH",
    "APP_CONFIG_STRICT",
    "BACKEND_HOST",
    "BACKEND_PORT",
    "BACKEND_RELOAD",
    "LOG_LEVEL",
    "LOG_JSON",
    "MCP_MAIN_URL",
    "LLM_LOCAL_QWEN_BASE_URL",
    "LLM_LOCAL_QWEN_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "MEMORY_STORE_CONFIG",
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
    assert settings.app_config_path is None
    assert settings.app_config_strict is False
    assert settings.log_json is True


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_DEBUG", "true")
    monkeypatch.setenv("APP_USECASE", "customer_support")
    monkeypatch.setenv("APP_CONFIG_PATH", "../config/usecases/customer_support.yaml")
    monkeypatch.setenv("APP_CONFIG_STRICT", "true")
    monkeypatch.setenv("BACKEND_HOST", "0.0.0.0")
    monkeypatch.setenv("BACKEND_PORT", "9000")
    monkeypatch.setenv("BACKEND_RELOAD", "true")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LOG_JSON", "false")
    monkeypatch.setenv("MEMORY_STORE_CONFIG", "../config/memory_store.yaml")

    settings = load_settings(env_file=None)

    assert settings.app_env == "test"
    assert settings.debug is True
    assert settings.app_usecase == "customer_support"
    assert settings.app_config_path == "../config/usecases/customer_support.yaml"
    assert settings.app_config_strict is True
    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert settings.reload is True
    assert settings.log_level == "DEBUG"
    assert settings.log_json is False
    assert settings.memory_store_config == "../config/memory_store.yaml"


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
