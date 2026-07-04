from __future__ import annotations

from flask import Flask, Response

def register_security_headers(app: Flask) -> None:
    @app.after_request
    def add_security_headers(response: Response) -> Response:
        response.headers.setdefault(
            "Content-Security-Policy",
            _build_content_security_policy(app),
        )
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), geolocation=(), microphone=()",
        )
        response.headers.setdefault("Cache-Control", "no-store")
        return response


def _build_content_security_policy(app: Flask) -> str:
    directives = {
        "default-src": ["'self'"],
        "img-src": ["'self'", "data:"],
        "style-src": ["'self'"],
        "script-src": ["'self'"],
        "font-src": ["'self'", "data:"],
        "connect-src": ["'self'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
        "frame-ancestors": ["'self'"],
        "object-src": ["'none'"],
    }
    return "; ".join(
        f"{name} {' '.join(values)}"
        for name, values in directives.items()
    )