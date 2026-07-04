from __future__ import annotations

from flask import Blueprint, abort, current_app, redirect, render_template, url_for

from app.services import HelpContent, load_help_content
from app.settings import Settings


pages_bp = Blueprint("pages", __name__)


def _get_settings() -> Settings:
    settings = current_app.config["FRONTEND_SETTINGS"]
    if not isinstance(settings, Settings):
        raise RuntimeError("Flask frontend settings were not loaded correctly.")
    return settings


@pages_bp.get("/")
def index() -> object:
    return redirect(url_for("pages.chat"))


@pages_bp.get("/chat")
def chat() -> str:
    return render_template("chat.html", active_page="chat")


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