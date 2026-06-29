"""Helpers that turn memory hits into bounded prompt context payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.contracts.memory import (
    MemoryChunkContextResult,
    MemoryPromptContext,
    MemoryRecord,
    MemoryResult,
    MemorySearchResult,
)
from app.memory.redaction import truncate_text


class MemoryContextBuilder:
    """Build bounded prompt context from search hits and optional chunk windows."""

    def __init__(
        self,
        *,
        max_total_chars: int,
        max_result_chars: int,
        include_sources: bool = True,
    ) -> None:
        self._max_total_chars = max_total_chars
        self._max_result_chars = max_result_chars
        self._include_sources = include_sources

    def build_context(
        self,
        *,
        search_result: MemorySearchResult | Sequence[MemoryResult],
        chunk_contexts: Mapping[str, MemoryChunkContextResult] | None = None,
    ) -> MemoryPromptContext:
        if self._max_total_chars <= 0 or self._max_result_chars <= 0:
            return MemoryPromptContext()

        items = self._sorted_results(search_result)
        snippets: list[str] = []
        included_ids: list[str] = []
        omitted_ids: list[str] = []
        included_context_ids: list[str] = []
        seen_dedup_keys: set[tuple[str, str]] = set()
        truncated = False

        for index, result in enumerate(items, start=1):
            dedup_key = self._dedup_key(result)
            if dedup_key in seen_dedup_keys:
                omitted_ids.append(result.memory_id)
                truncated = True
                continue
            seen_dedup_keys.add(dedup_key)

            available_chars = self._remaining_chars(snippets)
            chunk_context = self._resolve_chunk_context(result, chunk_contexts)
            snippet, context_ids, snippet_truncated = self._render_snippet(
                result=result,
                chunk_context=chunk_context,
                index=index,
                available_chars=available_chars,
            )
            if snippet is None:
                omitted_ids.append(result.memory_id)
                truncated = True
                continue

            snippets.append(snippet)
            included_ids.append(result.memory_id)
            for memory_id in context_ids:
                if memory_id not in included_context_ids:
                    included_context_ids.append(memory_id)
            truncated = truncated or snippet_truncated

        text = "\n\n".join(snippets)
        return MemoryPromptContext(
            text=text,
            included_memory_ids=tuple(included_context_ids),
            omitted_memory_ids=tuple(omitted_ids),
            total_chars=len(text),
            truncated=truncated,
            metadata={"result_count": len(included_ids)},
        )

    def _sorted_results(
        self,
        search_result: MemorySearchResult | Sequence[MemoryResult],
    ) -> list[MemoryResult]:
        items = list(search_result.results) if isinstance(search_result, MemorySearchResult) else list(search_result)
        return sorted(
            items,
            key=lambda item: (
                -(item.score if item.score is not None else -1.0),
                item.memory_id,
            ),
        )

    def _dedup_key(self, result: MemoryResult) -> tuple[str, str]:
        source_key = result.chunk_id or result.source_id or result.memory_id
        return source_key, result.text.strip().casefold()

    def _remaining_chars(self, snippets: Sequence[str]) -> int:
        if not snippets:
            return self._max_total_chars
        return self._max_total_chars - len("\n\n".join(snippets)) - 2

    def _resolve_chunk_context(
        self,
        result: MemoryResult,
        chunk_contexts: Mapping[str, MemoryChunkContextResult] | None,
    ) -> MemoryChunkContextResult | None:
        if chunk_contexts is None:
            return None
        if result.chunk_id is not None and result.chunk_id in chunk_contexts:
            return chunk_contexts[result.chunk_id]
        if result.memory_id in chunk_contexts:
            return chunk_contexts[result.memory_id]
        return None

    def _render_snippet(
        self,
        *,
        result: MemoryResult,
        chunk_context: MemoryChunkContextResult | None,
        index: int,
        available_chars: int,
    ) -> tuple[str | None, list[str], bool]:
        if available_chars <= 0:
            return None, [], True

        expanded_results = list(chunk_context.ordered_results) if chunk_context is not None else [result]
        header = self._render_header(result=result, index=index)
        body = self._render_body(expanded_results)

        if body == "":
            bounded_header = truncate_text(header, max_chars=available_chars)
            if bounded_header is None or bounded_header == "":
                return None, [], True
            return bounded_header, [item.memory_id for item in expanded_results], len(bounded_header) < len(header)

        max_body_chars = min(self._max_result_chars, max(available_chars - len(header) - 1, 0))
        if max_body_chars <= 0:
            return None, [], True

        bounded_body = truncate_text(body, max_chars=max_body_chars)
        if bounded_body is None or bounded_body == "":
            return None, [], True

        snippet = f"{header}\n{bounded_body}"
        if len(snippet) > available_chars:
            bounded_body = truncate_text(body, max_chars=max(available_chars - len(header) - 1, 0))
            if bounded_body is None or bounded_body == "":
                return None, [], True
            snippet = f"{header}\n{bounded_body}"

        return (
            snippet,
            [item.memory_id for item in expanded_results],
            bounded_body != body,
        )

    def _render_header(self, *, result: MemoryResult, index: int) -> str:
        kind = (result.memory_type or "memory").replace("_", " ")
        kind = kind[:1].upper() + kind[1:]
        parts: list[str] = []
        if self._include_sources:
            source_label = self._source_label(result.record)
            if source_label is not None:
                parts.append(f"source={source_label}")
            section_label = self._section_label(result.record)
            if section_label is not None:
                parts.append(f'section="{section_label}"')
        if result.score is not None:
            parts.append(f"score={result.score:.3f}")

        header = f"[{index}] {kind}"
        if parts:
            header = f"{header}, {', '.join(parts)}"
        return header

    def _render_body(self, results: Sequence[MemoryResult]) -> str:
        chunks: list[str] = []
        seen_ids: set[str] = set()
        for result in results:
            if result.memory_id in seen_ids:
                continue
            seen_ids.add(result.memory_id)
            text = result.text.strip()
            if text == "":
                continue
            chunks.append(text)
        return "\n\n".join(chunks)

    def _source_label(self, record: MemoryRecord | Mapping[str, Any] | None) -> str | None:
        if record is None:
            return None
        title = self._value(record, "title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        source = self._value(record, "source")
        source_title = self._value(source, "title")
        if isinstance(source_title, str) and source_title.strip():
            return source_title.strip()
        source_uri = self._value(source, "source_uri")
        if isinstance(source_uri, str) and source_uri.strip():
            return source_uri.strip()
        source_id = self._value(source, "source_id")
        if isinstance(source_id, str) and source_id.strip():
            return source_id.strip()
        return None

    def _section_label(self, record: MemoryRecord | Mapping[str, Any] | None) -> str | None:
        if record is None:
            return None
        source = self._value(record, "source")
        section_path = self._value(source, "section_path")
        if not isinstance(section_path, (tuple, list)) or not section_path:
            return None
        values = [item for item in section_path if isinstance(item, str) and item.strip()]
        if not values:
            return None
        return " > ".join(values)

    def _value(self, obj: object, key: str) -> object:
        if obj is None:
            return None
        if isinstance(obj, Mapping):
            return obj.get(key)
        return getattr(obj, key, None)


def build_memory_prompt_context(
    results: MemorySearchResult | Sequence[MemoryResult],
    *,
    max_total_chars: int,
    max_result_chars: int,
    chunk_contexts: Mapping[str, MemoryChunkContextResult] | None = None,
    include_sources: bool = True,
) -> MemoryPromptContext:
    """Render bounded memory snippets suitable for downstream prompt assembly."""

    return MemoryContextBuilder(
        max_total_chars=max_total_chars,
        max_result_chars=max_result_chars,
        include_sources=include_sources,
    ).build_context(search_result=results, chunk_contexts=chunk_contexts)


def build_memory_context(
    results: MemorySearchResult | Sequence[MemoryResult],
    *,
    max_total_chars: int,
    max_result_chars: int,
    chunk_contexts: Mapping[str, MemoryChunkContextResult] | None = None,
    include_sources: bool = True,
) -> str:
    """Backward-compatible text-only context helper."""

    return build_memory_prompt_context(
        results,
        max_total_chars=max_total_chars,
        max_result_chars=max_result_chars,
        chunk_contexts=chunk_contexts,
        include_sources=include_sources,
    ).text