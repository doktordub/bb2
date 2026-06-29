from __future__ import annotations

from pathlib import Path

import pytest

from app.config.loader import load_validated_config
from app.config.settings import load_settings
from app.config.view import ValidatedConfigurationView
from app.contracts.errors import ConfigurationError
from app.deployment.paths import resolve_deployment_paths
from app.deployment.startup import validate_deployment_startup


BACKEND_ROOT = Path(__file__).resolve().parents[3]
BASE_CONFIG_PATH = BACKEND_ROOT / "config" / "app.yaml"
FIXTURES_DIR = BACKEND_ROOT / "tests" / "fixtures" / "config"
VALID_MINIMAL_FIXTURE = FIXTURES_DIR / "valid_minimal.yaml"

ENV_VARS = (
    "APP_ENV",
    "APP_CONFIG_PATH",
    "APP_CONFIG_OVERRIDE_PATH",
    "APP_DATA_DIR",
    "APP_LOG_DIR",
    "APP_RUNTIME_DIR",
    "APP_PUBLIC_BASE_URL",
    "APP_GRACEFUL_SHUTDOWN_SECONDS",
    "BACKEND_HOST",
    "BACKEND_PORT",
    "APP_HOST",
    "APP_PORT",
    "METRICS_ENABLED",
    "METRICS_BIND_HOST",
    "METRICS_PORT",
)


def _build_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    app_env: str = "local",
) -> object:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("APP_DATA_DIR", (tmp_path / "data").as_posix())
    monkeypatch.setenv("APP_LOG_DIR", (tmp_path / "logs").as_posix())
    monkeypatch.setenv("APP_RUNTIME_DIR", (tmp_path / "runtime").as_posix())
    return load_settings(env_file=None)


def _load_config(settings: object, *, override_path: Path = VALID_MINIMAL_FIXTURE):
    parsed = load_validated_config(
        BASE_CONFIG_PATH,
        override_path=override_path,
        env=settings.environment_overrides(),
    )
    return ValidatedConfigurationView(parsed.model_dump(mode="python"))


def test_resolve_deployment_paths_returns_backend_owned_runtime_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _build_settings(monkeypatch, tmp_path)
    config = _load_config(settings)

    paths = resolve_deployment_paths(settings, config)

    assert paths.profile == "local"
    assert paths.data_dir == (tmp_path / "data").resolve(strict=False)
    assert paths.log_dir == (tmp_path / "logs").resolve(strict=False)
    assert paths.runtime_dir == (tmp_path / "runtime").resolve(strict=False)
    assert paths.workflow_state_path == (tmp_path / "data" / "workflow_state.db").resolve(strict=False)
    assert paths.trace_path == (tmp_path / "data" / "trace.db").resolve(strict=False)
    assert paths.memory_database_path == (tmp_path / "data" / "data" / "test-memory-store").resolve(strict=False)


def test_validate_deployment_startup_creates_local_runtime_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _build_settings(monkeypatch, tmp_path)
    config = _load_config(settings)

    state = validate_deployment_startup(settings, config)

    assert state.local_directory_bootstrap is True
    assert state.created_directory_count >= 3
    assert state.directories["data"].created is True
    assert state.directories["logs"].created is True
    assert state.directories["runtime"].created is True
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "logs").is_dir()
    assert (tmp_path / "runtime").is_dir()


def test_validate_deployment_startup_rejects_relative_sqlite_path_escape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _build_settings(monkeypatch, tmp_path)
    override_path = tmp_path / "deployment_path_escape.yaml"
    override_path.write_text(
        VALID_MINIMAL_FIXTURE.read_text(encoding="utf-8")
        + "\n"
        + "persistence:\n"
        + "  workflow_state:\n"
        + "    provider: sqlite\n"
        + "    sqlite:\n"
        + "      path: ../workflow_state.db\n",
        encoding="utf-8",
    )
    config = _load_config(settings, override_path=override_path)

    with pytest.raises(
        ConfigurationError,
        match="persistence.workflow_state.sqlite.path must not use parent-directory traversal",
    ):
        validate_deployment_startup(settings, config)