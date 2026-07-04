from pathlib import Path

import pytest

from app.settings import DEFAULT_HELP_MARKDOWN_PATH, load_settings


SETTINGS_ENV_VARS = [
    "FRONTEND_ENV",
    "FRONTEND_HOST",
    "FRONTEND_PORT",
    "FRONTEND_DEBUG",
    "FRONTEND_TESTING",
    "FRONTEND_SECRET_KEY",
    "BACKEND_BASE_URL",
    "BACKEND_TIMEOUT_SECONDS",
    "BACKEND_STREAM_TIMEOUT_SECONDS",
    "FRONTEND_ADMIN_ENABLED",
    "FRONTEND_DEBUG_TRACES_ENABLED",
    "FRONTEND_RESTART_ENABLED",
    "FRONTEND_HELP_MARKDOWN_PATH",
    "FRONTEND_STATIC_VERSION",
]


def test_load_settings_uses_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    settings = load_settings(load_env=False)

    assert settings.frontend_host == "127.0.0.1"
    assert settings.frontend_port == 5000
    assert settings.backend_base_url == "http://127.0.0.1:8000"
    assert settings.frontend_admin_enabled is True
    assert settings.frontend_restart_enabled is False
    assert settings.frontend_help_markdown_path == DEFAULT_HELP_MARKDOWN_PATH.resolve()


def test_load_settings_resolves_relative_help_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    relative_help_path = tmp_path / "guides" / "help.md"
    relative_help_path.parent.mkdir(parents=True)
    relative_help_path.write_text("# Help", encoding="utf-8")

    monkeypatch.setenv("FRONTEND_HELP_MARKDOWN_PATH", relative_help_path.as_posix())
    settings = load_settings(load_env=False)

    assert settings.frontend_help_markdown_path == relative_help_path.resolve()


def test_load_settings_honors_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    help_path = tmp_path / "custom-help.md"
    help_path.write_text("# Help", encoding="utf-8")

    monkeypatch.setenv("FRONTEND_HOST", "0.0.0.0")
    monkeypatch.setenv("FRONTEND_PORT", "5050")
    monkeypatch.setenv("FRONTEND_DEBUG", "true")
    monkeypatch.setenv("FRONTEND_TESTING", "true")
    monkeypatch.setenv("BACKEND_BASE_URL", "http://backend.internal:9000/")
    monkeypatch.setenv("BACKEND_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("BACKEND_STREAM_TIMEOUT_SECONDS", "180")
    monkeypatch.setenv("FRONTEND_ADMIN_ENABLED", "false")
    monkeypatch.setenv("FRONTEND_DEBUG_TRACES_ENABLED", "false")
    monkeypatch.setenv("FRONTEND_RESTART_ENABLED", "true")
    monkeypatch.setenv("FRONTEND_HELP_MARKDOWN_PATH", help_path.as_posix())
    monkeypatch.setenv("FRONTEND_STATIC_VERSION", "phase-13")

    settings = load_settings(load_env=False)

    assert settings.frontend_host == "0.0.0.0"
    assert settings.frontend_port == 5050
    assert settings.frontend_debug is True
    assert settings.frontend_testing is True
    assert settings.backend_base_url == "http://backend.internal:9000"
    assert settings.backend_timeout_seconds == 45
    assert settings.backend_stream_timeout_seconds == 180
    assert settings.frontend_admin_enabled is False
    assert settings.frontend_debug_traces_enabled is False
    assert settings.frontend_restart_enabled is True
    assert settings.frontend_help_markdown_path == help_path.resolve()
    assert settings.frontend_static_version == "phase-13"


def test_load_settings_invalid_values_fall_back_to_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_PORT", "not-a-port")
    monkeypatch.setenv("BACKEND_TIMEOUT_SECONDS", "forever")
    monkeypatch.setenv("BACKEND_STREAM_TIMEOUT_SECONDS", "still-forever")
    monkeypatch.setenv("FRONTEND_DEBUG", "sometimes")
    monkeypatch.setenv("FRONTEND_RESTART_ENABLED", "maybe")

    settings = load_settings(load_env=False)

    assert settings.frontend_port == 5000
    assert settings.backend_timeout_seconds == 90
    assert settings.backend_stream_timeout_seconds == 300
    assert settings.frontend_debug is False
    assert settings.frontend_restart_enabled is False