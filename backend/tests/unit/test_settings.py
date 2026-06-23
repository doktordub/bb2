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
    assert settings.app_config_path == "config/app.yaml"
    assert settings.app_config_override_path == "config/app.local.yaml"
    assert settings.app_data_dir == "data"
    assert settings.app_config_strict is False
    assert settings.log_json is True
    assert settings.resolved_app_config_path == (BACKEND_ROOT / "config/app.yaml").resolve()
    assert settings.resolved_app_config_override_path == (
        BACKEND_ROOT / "config/app.local.yaml"
    ).resolve()
    assert settings.resolved_app_data_dir == (BACKEND_ROOT / "data").resolve()


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_DEBUG", "true")
    monkeypatch.setenv("APP_USECASE", "customer_support")
    monkeypatch.setenv("APP_CONFIG_PATH", "config/test/base.yaml")
    monkeypatch.setenv("APP_CONFIG_OVERRIDE_PATH", "config/test/override.yaml")
    monkeypatch.setenv("APP_DATA_DIR", "var/data")
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
    assert settings.app_config_path == "config/test/base.yaml"
    assert settings.app_config_override_path == "config/test/override.yaml"
    assert settings.app_data_dir == "var/data"
    assert settings.app_config_strict is True
    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert settings.reload is True
    assert settings.log_level == "DEBUG"
    assert settings.log_json is False
    assert settings.memory_store_config == "../config/memory_store.yaml"
    assert settings.resolved_app_config_path == (BACKEND_ROOT / "config/test/base.yaml").resolve()
    assert settings.resolved_app_config_override_path == (
        BACKEND_ROOT / "config/test/override.yaml"
    ).resolve()
    assert settings.resolved_app_data_dir == (BACKEND_ROOT / "var/data").resolve()


def test_settings_path_fields_fall_back_to_defaults_when_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_env(monkeypatch)
    monkeypatch.setenv("APP_CONFIG_PATH", "   ")
    monkeypatch.setenv("APP_CONFIG_OVERRIDE_PATH", "")
    monkeypatch.setenv("APP_DATA_DIR", "\t")

    settings = load_settings(env_file=None)

    assert settings.app_config_path == "config/app.yaml"
    assert settings.app_config_override_path == "config/app.local.yaml"
    assert settings.app_data_dir == "data"


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
