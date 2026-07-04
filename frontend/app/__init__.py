from __future__ import annotations

from flask import Flask, render_template

from app.errors import BackendUnavailableError
from app.routes import admin_api_bp, pages_bp, ui_api_bp
from app.security import register_security_headers
from app.services import build_backend_client
from app.settings import Settings, load_settings


def create_app(settings: Settings | None = None) -> Flask:
    resolved_settings = settings or load_settings()

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_mapping(resolved_settings.as_flask_config())
    app.jinja_env.globals["frontend_app_name"] = "Pluggable Agentic AI"
    app.extensions["backend_client"] = build_backend_client(resolved_settings)

    app.register_blueprint(pages_bp)
    app.register_blueprint(ui_api_bp)
    app.register_blueprint(admin_api_bp)
    register_security_headers(app)
    _register_context_processors(app)
    _register_error_handlers(app)

    return app


def _register_context_processors(app: Flask) -> None:
    @app.context_processor
    def inject_shell_context() -> dict[str, object]:
        settings = app.config["FRONTEND_SETTINGS"]
        return {
            "frontend_settings": settings,
            "static_version": settings.frontend_static_version,
        }


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_error: Exception) -> tuple[str, int]:
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_server_error(_error: Exception) -> tuple[str, int]:
        return render_template("errors/500.html"), 500

    @app.errorhandler(BackendUnavailableError)
    def backend_unavailable(error: BackendUnavailableError) -> tuple[str, int]:
        return render_template("errors/503.html", error_message=str(error)), 503