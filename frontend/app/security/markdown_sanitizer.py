from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import bleach
from markdown import Markdown


_ALLOWED_TAGS = frozenset(
    set(bleach.sanitizer.ALLOWED_TAGS).union(
        {
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "hr",
            "p",
            "pre",
            "code",
            "blockquote",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
        }
    )
)

_ALLOWED_ATTRIBUTES: dict[str, list[str]] = {
    "a": ["href", "title"],
    "h1": ["id"],
    "h2": ["id"],
    "h3": ["id"],
    "h4": ["id"],
    "h5": ["id"],
    "h6": ["id"],
    "ol": ["start"],
    "th": ["colspan", "rowspan", "scope"],
    "td": ["colspan", "rowspan"],
}

_ALLOWED_PROTOCOLS = frozenset(set(bleach.sanitizer.ALLOWED_PROTOCOLS).union({"mailto"}))
_MARKDOWN_EXTENSIONS = ["fenced_code", "sane_lists", "tables", "toc"]
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class MarkdownHeading:
    level: int
    anchor: str
    text: str


@dataclass(frozen=True, slots=True)
class RenderedMarkdown:
    html: str
    headings: tuple[MarkdownHeading, ...]


def render_safe_markdown(raw_text: str) -> RenderedMarkdown:
    markdown = Markdown(extensions=_MARKDOWN_EXTENSIONS)
    rendered_html = markdown.convert(raw_text)
    headings = tuple(_flatten_toc_tokens(getattr(markdown, "toc_tokens", [])))
    cleaner = bleach.Cleaner(
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        protocols=_ALLOWED_PROTOCOLS,
        strip=True,
    )
    return RenderedMarkdown(
        html=cleaner.clean(rendered_html),
        headings=headings,
    )


def _flatten_toc_tokens(tokens: list[dict[str, Any]]) -> list[MarkdownHeading]:
    headings: list[MarkdownHeading] = []
    for token in tokens:
        anchor = str(token.get("id") or "").strip()
        if anchor:
            headings.append(
                MarkdownHeading(
                    level=int(token.get("level") or 1),
                    anchor=anchor,
                    text=_strip_html(str(token.get("name") or token.get("html") or anchor)),
                )
            )
        children = token.get("children") or []
        if isinstance(children, list):
            headings.extend(_flatten_toc_tokens(children))
    return headings


def _strip_html(value: str) -> str:
    return _TAG_RE.sub("", value).strip()