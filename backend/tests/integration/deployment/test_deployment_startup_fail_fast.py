from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.contracts.errors import ConfigurationError
from app.main import create_app


BACKEND_ROOT = Path(__file__).resolve().parents[3]
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
    "BACKEND_HOST",
    "BACKEND_PORT",
    "APP_HOST",
    "APP_PORT",
)


def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_create_app_fails_fast_for_staging_missing_runtime_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_env(monkeypatch)
    data_dir = tmp_path / "staging-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    log_dir = tmp_path / "staging-logs"
    runtime_dir = tmp_path / "staging-runtime"
    override_path = tmp_path / "staging_missing_runtime_dirs.yaml"
    override_path.write_text(
        VALID_MINIMAL_FIXTURE.read_text(encoding="utf-8")
        + "\n"
        + "app:\n"
        + "  environment: staging\n"
        + "deployment:\n"
        + "  profile: staging\n"
        + f"  log_dir: {log_dir.as_posix()}\n"
        + f"  runtime_dir: {runtime_dir.as_posix()}\n"
        + "persistence:\n"
        + f"  base_dir: {data_dir.as_posix()}\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("APP_CONFIG_PATH", "config/app.yaml")
    monkeypatch.setenv("APP_CONFIG_OVERRIDE_PATH", override_path.as_posix())

    app = create_app(load_settings(env_file=None))

    with pytest.raises(
        ConfigurationError,
        match="deployment.log_dir does not exist and cannot be created automatically in staging profile",
    ):
        with TestClient(app):
            pass


def test_create_app_fails_fast_for_backend_root_writes_in_production(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_env(monkeypatch)
    outside_data_dir = tmp_path / "production-data"
    outside_data_dir.mkdir(parents=True, exist_ok=True)
    unsafe_log_dir = BACKEND_ROOT / "logs-prod"
    unsafe_runtime_dir = tmp_path / "runtime-prod"
    unsafe_runtime_dir.mkdir(parents=True, exist_ok=True)
    override_path = tmp_path / "production_backend_root_write.yaml"
    override_path.write_text(
        VALID_MINIMAL_FIXTURE.read_text(encoding="utf-8")
        + "\n"
        + "app:\n"
        + "  environment: production\n"
        + "deployment:\n"
        + "  profile: production\n"
        + f"  log_dir: {unsafe_log_dir.as_posix()}\n"
        + f"  runtime_dir: {unsafe_runtime_dir.as_posix()}\n"
        + "persistence:\n"
        + f"  base_dir: {outside_data_dir.as_posix()}\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_CONFIG_PATH", "config/app.yaml")
    monkeypatch.setenv("APP_CONFIG_OVERRIDE_PATH", override_path.as_posix())

    app = create_app(load_settings(env_file=None))

    with pytest.raises(
        ConfigurationError,
        match="deployment.log_dir must not resolve inside backend/ in production profile",
    ):
        with TestClient(app):
            pass