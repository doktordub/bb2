from pathlib import Path


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = FRONTEND_ROOT / "app" / "static"
STATIC_JS_ROOT = STATIC_ROOT / "js"
STATIC_CSS_ROOT = STATIC_ROOT / "css"

LEGACY_PAGE_ASSETS = (
    STATIC_JS_ROOT / "chat-page.js",
    STATIC_JS_ROOT / "admin-page.js",
    STATIC_JS_ROOT / "help-page.js",
    STATIC_CSS_ROOT / "chat.css",
    STATIC_CSS_ROOT / "admin.css",
    STATIC_CSS_ROOT / "help.css",
)


def test_legacy_flat_page_assets_are_removed() -> None:
    lingering_assets = [
        path.relative_to(FRONTEND_ROOT).as_posix()
        for path in LEGACY_PAGE_ASSETS
        if path.exists()
    ]

    assert not lingering_assets, (
        "Legacy flat page assets should stay removed: "
        f"{', '.join(lingering_assets)}"
    )


def test_static_asset_roots_remain_directory_only() -> None:
    top_level_js = sorted(
        path.relative_to(FRONTEND_ROOT).as_posix()
        for path in STATIC_JS_ROOT.glob("*.js")
    )
    top_level_css = sorted(
        path.relative_to(FRONTEND_ROOT).as_posix()
        for path in STATIC_CSS_ROOT.glob("*.css")
    )

    assert not top_level_js, (
        "Add JavaScript assets under app/static/js/<owner>/ instead of reintroducing top-level files: "
        f"{', '.join(top_level_js)}"
    )
    assert not top_level_css, (
        "Add CSS assets under app/static/css/<owner>/ instead of reintroducing top-level files: "
        f"{', '.join(top_level_css)}"
    )