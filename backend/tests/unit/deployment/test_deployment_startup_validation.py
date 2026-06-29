from __future__ import annotations

from pathlib import Path

import pytest

from app.config.loader import load_validated_config
from app.config.settings import load_settings
from app.config.view import ValidatedConfigurationView
from app.contracts.errors import ConfigurationError
from app.deployment.diagnostics import build_safe_deployment_summary
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
    "BACKEND_HOST",
    "BACKEND_PORT",
    "APP_HOST",
    "APP_PORT",
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


def test_validate_deployment_startup_builds_safe_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _build_settings(monkeypatch, tmp_path)
    config = _load_config(settings)

    startup_state = validate_deployment_startup(settings, config)
    summary = build_safe_deployment_summary(startup_state)

    assert summary["profile"] == "local"
    assert summary["runtime_paths_valid"] is True
    assert summary["policy_safe"] is True
    assert summary["workflow_state_configured"] is True
    assert summary["trace_configured"] is True
    assert summary["memory_configured"] is True
    assert summary["created_directory_count"] >= 3
    assert summary["directories"]["logs"]["ready"] is True
    assert summary["directories"]["runtime"]["ready"] is True
    assert tmp_path.as_posix() not in str(summary)
    assert BACKEND_ROOT.as_posix() not in str(summary)


def test_validate_deployment_startup_rejects_unsafe_production_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = _build_settings(monkeypatch, tmp_path, app_env="production")
    data_dir = tmp_path / "data-prod"
    log_dir = tmp_path / "logs-prod"
    runtime_dir = tmp_path / "runtime-prod"
    data_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    override_path = tmp_path / "unsafe_production_policy.yaml"
    override_path.write_text(
        VALID_MINIMAL_FIXTURE.read_text(encoding="utf-8")
        + "\n"
        + "app:\n"
        + "  environment: production\n"
        + "deployment:\n"
        + "  profile: production\n"
        + f"  log_dir: {log_dir.as_posix()}\n"
        + f"  runtime_dir: {runtime_dir.as_posix()}\n"
        + "persistence:\n"
        + f"  base_dir: {data_dir.as_posix()}\n"
        + "policy:\n"
        + "  enabled: false\n",
        encoding="utf-8",
    )
    config = _load_config(settings, override_path=override_path)

    with pytest.raises(
        ConfigurationError,
        match="deployment startup requires policy.enabled=true",
    ):
        validate_deployment_startup(settings, config)