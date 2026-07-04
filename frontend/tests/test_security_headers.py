from pathlib import Path

import pytest

from app import create_app
from app.settings import load_settings


def test_security_headers_are_applied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    help_path = tmp_path / "Training_Readme.md"
    help_path.write_text("# Training\n\nDocs.", encoding="utf-8")

    monkeypatch.setenv("FRONTEND_TESTING", "true")
    monkeypatch.setenv("FRONTEND_HELP_MARKDOWN_PATH", help_path.as_posix())

    app = create_app(load_settings(load_env=False))

    with app.test_client() as client:
        response = client.get("/chat")

    assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["Permissions-Policy"] == "camera=(), geolocation=(), microphone=()"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert response.headers["Cache-Control"] == "no-store"