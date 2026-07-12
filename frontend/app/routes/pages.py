from __future__ import annotations

import json

from flask import Blueprint, abort, current_app, redirect, render_template, url_for

from app.services import HelpContent, load_help_content
from app.settings import Settings, WORKSPACE_ROOT


pages_bp = Blueprint("pages", __name__)
VISUALIZATION_FIXTURE_PATH = (
    WORKSPACE_ROOT / "backend" / "tests" / "fixtures" / "visualization" / "chart_artifact_v1.json"
)
VISUALIZATION_CASES_PATH = (
    WORKSPACE_ROOT / "backend" / "tests" / "fixtures" / "visualization" / "chart_validation_cases_v1.json"
)


def _get_settings() -> Settings:
    settings = current_app.config["FRONTEND_SETTINGS"]
    if not isinstance(settings, Settings):
        raise RuntimeError("Flask frontend settings were not loaded correctly.")
    return settings


def _load_visualization_fixture() -> dict[str, object]:
    return json.loads(VISUALIZATION_FIXTURE_PATH.read_text(encoding="utf-8"))


def _load_visualization_cases() -> dict[str, object]:
    return json.loads(VISUALIZATION_CASES_PATH.read_text(encoding="utf-8"))


@pages_bp.get("/")
def index() -> object:
    return redirect(url_for("pages.chat"))


@pages_bp.get("/chat")
def chat() -> str:
    return render_template("chat.html", active_page="chat")


@pages_bp.get("/visualization-foundation")
def visualization_foundation() -> str:
    return render_template(
        "visualization_foundation.html",
        active_page="visualization-foundation",
        visualization_fixture=_load_visualization_cases(),
    )


@pages_bp.get("/admin")
def admin() -> str:
    settings = _get_settings()
    if not settings.frontend_admin_enabled:
        abort(404)
    return render_template("admin.html", active_page="admin")


@pages_bp.get("/help")
def help_page() -> str:
    help_content: HelpContent = load_help_content(_get_settings())
    return render_template(
        "help.html",
        active_page="help",
        help_content=help_content,
    )