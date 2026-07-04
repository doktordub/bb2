from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.security import MarkdownHeading, render_safe_markdown
from app.settings import Settings


@dataclass(frozen=True, slots=True)
class HelpContent:
    source_path: Path
    exists: bool
    title: str
    summary: str
    html: str
    toc: tuple[MarkdownHeading, ...]


class HelpContentService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def load(self) -> HelpContent:
        source_path = self._settings.frontend_help_markdown_path
        if not source_path.exists() or not source_path.is_file():
            return HelpContent(
                source_path=source_path,
                exists=False,
                title="Training guide unavailable",
                summary="Configure FRONTEND_HELP_MARKDOWN_PATH to a readable Markdown file.",
                html="",
                toc=(),
            )

        raw_text = source_path.read_text(encoding="utf-8")
        rendered = render_safe_markdown(raw_text)
        return HelpContent(
            source_path=source_path,
            exists=True,
            title=_extract_title(raw_text, source_path.stem),
            summary=_extract_summary(raw_text),
            html=rendered.html,
            toc=rendered.headings,
        )


def load_help_content(settings: Settings) -> HelpContent:
    return HelpContentService(settings).load()


def _extract_title(raw_text: str, fallback: str) -> str:
    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
    return fallback


def _extract_summary(raw_text: str) -> str:
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped
    return "Open the table of contents or use search to navigate this training guide."