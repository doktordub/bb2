from __future__ import annotations

from app import create_app
from app.settings import Settings


app = create_app()


def main() -> None:
    settings = app.config["FRONTEND_SETTINGS"]
    if not isinstance(settings, Settings):
        raise RuntimeError("Flask frontend settings were not loaded correctly.")

    app.run(
        host=settings.frontend_host,
        port=settings.frontend_port,
        debug=settings.frontend_debug,
    )


if __name__ == "__main__":
    main()