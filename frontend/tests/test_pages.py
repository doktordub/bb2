from pathlib import Path

import pytest

from app import create_app
from app.settings import load_settings


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


def build_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, admin_enabled: bool = True):
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    help_path = tmp_path / "Training_Readme.md"
    help_path.write_text("# Training\n\nLocal help preview.", encoding="utf-8")

    monkeypatch.setenv("FRONTEND_TESTING", "true")
    monkeypatch.setenv("FRONTEND_ADMIN_ENABLED", "true" if admin_enabled else "false")
    monkeypatch.setenv("FRONTEND_HELP_MARKDOWN_PATH", help_path.as_posix())

    app = create_app(load_settings(load_env=False))
    return app.test_client()


def test_root_redirects_to_chat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = build_client(monkeypatch, tmp_path)

    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/chat")


def test_primary_pages_render(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = build_client(monkeypatch, tmp_path)

    assert client.get("/chat").status_code == 200
    assert client.get("/admin").status_code == 200
    assert client.get("/help").status_code == 200
    assert client.get("/visualization-foundation").status_code == 200


def test_shared_shell_renders_nav_and_status_chip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = build_client(monkeypatch, tmp_path)

    response = client.get("/chat")

    assert response.status_code == 200
    assert b"Agent workflow shell" in response.data
    assert b"data-backend-status-chip" in response.data
    assert b"Theme: Auto" in response.data


def test_chat_page_renders_phase_9_workspace_shell(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = build_client(monkeypatch, tmp_path)

    response = client.get("/chat")

    assert response.status_code == 200
    assert b"Chat runtime status" in response.data
    assert b"data-chat-session-label" in response.data
    assert b"data-chat-trace-label" in response.data
    assert b"data-chat-agent-label" in response.data
    assert b"data-chat-strategy-label" in response.data
    assert b"data-chat-session-kpis-slot" in response.data
    assert b"data-chat-composer" in response.data
    assert b"data-usecase-select" in response.data
    assert b"data-chat-panel-open=\"sessions\"" in response.data
    assert b"data-panel-drawer=\"inspector\"" in response.data
    assert b"data-session-new-chat" in response.data
    assert b"data-session-context" in response.data
    assert b"data-session-reset" in response.data
    assert b"data-conversation-thread" in response.data
    assert b"data-chat-loading-state" in response.data
    assert b"data-visualization-max-artifacts=\"3\"" in response.data
    assert b"data-visualization-max-rows-inline=\"5000\"" in response.data
    assert b"data-visualization-max-series=\"12\"" in response.data
    assert b"data-visualization-max-categories=\"100\"" in response.data
    assert b"loading..." in response.data
    assert b"conversation-header-row" in response.data
    assert b"data-chat-live-region" in response.data
    assert b"data-chat-confirm-dialog" in response.data
    assert b"data-retry-button" in response.data
    assert b"data-open-trace-button" in response.data
    assert b"data-capabilities-summary" in response.data
    assert b"data-inspector-future" in response.data
    assert b"css/pages/chat/index.css" in response.data
    assert b"css/chat.css" not in response.data
    assert b"vendor/echarts/echarts-5.5.1.min.js" in response.data
    assert b"js/chat/index.js" in response.data
    assert b"js/chat-page.js" not in response.data
    assert b"data-health-banner" not in response.data
    assert b"data-chat-offline-card" not in response.data


def test_visualization_foundation_page_renders_phase_1_fixture_harness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = build_client(monkeypatch, tmp_path)

    response = client.get("/visualization-foundation")

    assert response.status_code == 200
    assert b"Visualization foundation" in response.data
    assert b"data-visualization-demo-grid" in response.data
    assert b"data-visualization-supported" in response.data
    assert b"chart_grouped_bar_income_expense" in response.data
    assert b"chart_table_monthly_status" in response.data
    assert b"vendor/echarts/echarts-5.5.1.min.js" in response.data
    assert b"js/visualization/index.js" in response.data


def test_admin_page_renders_phase_12_tabbed_console(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = build_client(monkeypatch, tmp_path)

    response = client.get("/admin")

    assert response.status_code == 200
    assert b"Admin runtime summary" in response.data
    assert b"Admin sections" in response.data
    assert b"data-admin-tab=\"health\"" in response.data
    assert b"data-admin-panel=\"debug\"" in response.data
    assert b"Capability snapshot" in response.data
    assert b"data-admin-health-pill" in response.data
    assert b"data-admin-trace-button" in response.data
    assert b"data-admin-trace-form" in response.data
    assert b"data-admin-trace-results" in response.data
    assert b"data-admin-health-json" in response.data
    assert b"data-admin-visualization-enabled" in response.data
    assert b"data-admin-visualization-backend-types" in response.data
    assert b"data-admin-visualization-mismatches" in response.data
    assert b"css/pages/admin/index.css" in response.data
    assert b"css/admin.css" not in response.data
    assert b"js/admin/index.js" in response.data
    assert b"js/admin-page.js" not in response.data
    assert b"data-admin-health-banner" not in response.data


def test_help_page_renders_sanitized_markdown_shell(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = build_client(monkeypatch, tmp_path)

    response = client.get("/help")

    assert response.status_code == 200
    assert b"Help workspace" in response.data
    assert b"data-help-search" in response.data
    assert b"data-help-content" in response.data
    assert b"Local help preview." in response.data
    assert b"css/pages/help/index.css" in response.data
    assert b"css/help.css" not in response.data
    assert b"js/help/index.js" in response.data
    assert b"js/help-page.js" not in response.data


def test_help_page_handles_missing_markdown_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("FRONTEND_TESTING", "true")
    monkeypatch.setenv("FRONTEND_HELP_MARKDOWN_PATH", (tmp_path / "missing.md").as_posix())

    app = create_app(load_settings(load_env=False))
    client = app.test_client()

    response = client.get("/help")

    assert response.status_code == 200
    assert b"Training guide unavailable" in response.data
    assert b"safe empty state" in response.data


def test_admin_page_respects_feature_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = build_client(monkeypatch, tmp_path, admin_enabled=False)

    response = client.get("/admin")

    assert response.status_code == 404


def test_not_found_page_renders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = build_client(monkeypatch, tmp_path)

    response = client.get("/missing")

    assert response.status_code == 404
    assert b"Page not found" in response.data


def test_internal_error_page_renders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    help_path = tmp_path / "Training_Readme.md"
    help_path.write_text("# Training\n\nLocal help preview.", encoding="utf-8")

    monkeypatch.setenv("FRONTEND_HELP_MARKDOWN_PATH", help_path.as_posix())

    app = create_app(load_settings(load_env=False))
    app.config.update(TESTING=False, PROPAGATE_EXCEPTIONS=False)

    @app.get("/boom")
    def boom() -> str:
        raise RuntimeError("boom")

    client = app.test_client()

    response = client.get("/boom")

    assert response.status_code == 500
    assert b"Frontend error" in response.data