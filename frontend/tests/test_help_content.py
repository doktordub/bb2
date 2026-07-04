from pathlib import Path

from app.services import load_help_content
from app.settings import Settings


def build_settings(help_path: Path) -> Settings:
    return Settings(
        frontend_env="test",
        frontend_host="127.0.0.1",
        frontend_port=5000,
        frontend_debug=False,
        frontend_testing=True,
        frontend_secret_key="test-secret",
        backend_base_url="http://127.0.0.1:8000",
        backend_timeout_seconds=90,
        backend_stream_timeout_seconds=300,
        frontend_admin_enabled=True,
        frontend_debug_traces_enabled=True,
        frontend_restart_enabled=False,
        frontend_help_markdown_path=help_path,
        frontend_static_version="test",
    )


def test_load_help_content_reads_title_and_summary(tmp_path: Path) -> None:
    source_path = tmp_path / "help.md"
    source_path.write_text("# Training Guide\n\nUse the chat page for Q&A.", encoding="utf-8")

    help_content = load_help_content(build_settings(source_path))

    assert help_content.exists is True
    assert help_content.title == "Training Guide"
    assert help_content.summary == "Use the chat page for Q&A."
    assert "<h1 id=\"training-guide\">" in help_content.html
    assert help_content.toc[0].anchor == "training-guide"


def test_load_help_content_sanitizes_rendered_markdown(tmp_path: Path) -> None:
    source_path = tmp_path / "help.md"
    source_path.write_text(
        "# Training Guide\n\n"
        "<script>alert('x')</script>\n\n"
        "## Table\n\n"
        "| Name | Value |\n"
        "| --- | --- |\n"
        "| safe | yes |\n\n"
        "```mermaid\n"
        "graph TD; A-->B;\n"
        "```\n\n"
        "<a href=\"javascript:alert('x')\" onclick=\"boom()\">bad</a>",
        encoding="utf-8",
    )

    help_content = load_help_content(build_settings(source_path))

    assert "<script" not in help_content.html
    assert "onclick=" not in help_content.html
    assert "javascript:alert" not in help_content.html
    assert "<table>" in help_content.html
    assert "<pre><code>graph TD; A--&gt;B;" in help_content.html
    assert [heading.text for heading in help_content.toc] == ["Training Guide", "Table"]


def test_load_help_content_handles_missing_file(tmp_path: Path) -> None:
    help_content = load_help_content(build_settings(tmp_path / "missing.md"))

    assert help_content.exists is False
    assert help_content.title == "Training guide unavailable"
    assert help_content.html == ""
    assert help_content.toc == ()