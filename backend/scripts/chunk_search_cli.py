"""CLI utility to search document chunks from backend-configured memory."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.contracts.memory import MemoryChunkContextRequest, MemorySearchFilters, MemorySearchRequest
from app.memory.cli_support import (
    DEFAULT_CONFIG_PATH,
    MemoryCliError,
    cli_scope_payload,
    cli_scope_resolution_payload,
    close_memory_runtime,
    format_cli_scope_summary,
    load_memory_runtime,
    resolve_cli_scope,
)

SNIPPET_LENGTH = 240
TITLE_LENGTH = 72


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search the backend-configured memory store for document chunks."
    )
    parser.add_argument("query", help="Search text to match against chunk content.")
    parser.add_argument(
        "--config-path",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Backend config file to load. Default: {DEFAULT_CONFIG_PATH}",
    )
    parser.add_argument("--user-id", default="", help="Scope user_id. Default: empty.")
    parser.add_argument(
        "--project-id",
        default="",
        help="Scope project_id. Default: resolve from configured docs memory scope.",
    )
    parser.add_argument("--agent-id", default="", help="Scope agent_id. Default: unset.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max results to return. Defaults to the configured backend search top-k.",
    )
    parser.add_argument(
        "--before",
        type=int,
        default=0,
        help="Context chunks to include before a hit. Default: 0.",
    )
    parser.add_argument(
        "--after",
        type=int,
        default=0,
        help="Context chunks to include after a hit. Default: 0.",
    )
    return parser.parse_args()


def clean_text(value: Any) -> str:
    return str(value or "").replace("\ufeff", "").strip()


def truncate_text(value: Any, limit: int) -> str:
    text = clean_text(value)
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def resolve_limit(user_limit: int | None, *, default_limit: int, max_limit: int) -> int:
    if user_limit is None:
        return min(default_limit, max_limit)
    if user_limit < 1:
        raise MemoryCliError("Search limit must be at least 1.", exit_code=2)
    return min(user_limit, max_limit)


def normalize_chunk_result(result: Any) -> dict[str, Any]:
    record = result.record
    source = getattr(record, "source", None)
    heading_path = list(getattr(source, "section_path", None) or [])
    text = clean_text(record.text)
    summary = clean_text(record.summary)
    source_uri = clean_text(getattr(source, "source_uri", None) or getattr(source, "source_id", None))
    source_id = clean_text(getattr(source, "source_id", None)) or source_uri
    document_id = clean_text(getattr(source, "document_id", None)) or source_uri or source_id
    document_chunk_index = getattr(source, "chunk_index", None)
    title = (
        clean_text(record.title)
        or (heading_path[-1] if heading_path else None)
        or truncate_text(text, TITLE_LENGTH)
        or "Untitled chunk"
    )
    score_details = getattr(result, "score_details", None)
    final_score = getattr(score_details, "final_score", None) if score_details is not None else None
    if final_score is None:
        final_score = getattr(result, "score", None)
    score = float(final_score or 0.0)
    component_scores = {}
    if score_details is not None:
        component_scores = dict(getattr(score_details, "component_scores", {}) or {})

    payload = {
        "memory_id": result.memory_id,
        "chunk_id": record.chunk_id,
        "title": title,
        "summary": summary,
        "text": text,
        "snippet": summary or truncate_text(text, SNIPPET_LENGTH),
        "source_uri": source_uri,
        "source_id": source_id,
        "document_id": document_id,
        "heading_path": heading_path,
        "heading_path_label": " / ".join(heading_path),
        "document_chunk_index": document_chunk_index,
        "score": round(score, 4),
        "score_label": f"{score:.3f}",
    }
    if component_scores:
        payload["component_scores"] = component_scores
    return payload


def normalize_context_result(result: Any) -> dict[str, Any]:
    record = result.record
    source = getattr(record, "source", None)
    return {
        "memory_id": result.memory_id,
        "chunk_id": record.chunk_id,
        "title": clean_text(record.title) or truncate_text(record.text, TITLE_LENGTH),
        "source_uri": clean_text(
            getattr(source, "source_uri", None) or getattr(source, "source_id", None)
        ),
        "document_chunk_index": getattr(source, "chunk_index", None),
        "text": clean_text(record.text),
    }


def print_payload(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2))


async def run() -> int:
    args = parse_args()
    runtime = await load_memory_runtime(args.config_path)
    scope_resolution = resolve_cli_scope(
        runtime.config,
        project_id=args.project_id,
        user_id=args.user_id,
        agent_id=args.agent_id,
    )
    scope = scope_resolution.scope
    limit = resolve_limit(
        args.limit,
        default_limit=runtime.search_limit_default,
        max_limit=runtime.search_limit_max,
    )

    try:
        for line in format_cli_scope_summary(scope_resolution):
            print(line, file=sys.stderr)
        results = await runtime.adapter.search(
            MemorySearchRequest(
                text=args.query,
                scope=scope,
                filters=MemorySearchFilters(
                    kinds=("document_chunk",),
                    status=("active",),
                ),
                include_document_chunks=True,
                limit=limit,
            )
        )
        items = [normalize_chunk_result(result) for result in results.results]
        if args.before > 0 or args.after > 0:
            for item, result in zip(items, results.results, strict=True):
                if not result.chunk_id:
                    continue
                context = await runtime.adapter.get_chunk_context(
                    MemoryChunkContextRequest(
                        chunk_id=result.chunk_id,
                        scope=scope,
                        before=args.before,
                        after=args.after,
                    )
                )
                if context is None:
                    continue
                item["context"] = {
                    "before": [normalize_context_result(chunk) for chunk in context.before],
                    "after": [normalize_context_result(chunk) for chunk in context.after],
                }
    finally:
        await close_memory_runtime(runtime)

    payload = {
        "ok": True,
        "message": f"Found {len(items)} chunk result(s).",
        "query": args.query,
        "database_path": (
            None if runtime.database_path is None else str(runtime.database_path.resolve(strict=False))
        ),
        "scope": cli_scope_payload(scope),
        "requested_scope": {
            "user_id": args.user_id,
            "project_id": args.project_id,
            "agent_id": args.agent_id,
        },
        "scope_resolution": cli_scope_resolution_payload(scope_resolution),
        "limit": limit,
        "limit_max": runtime.search_limit_max,
        "before": args.before,
        "after": args.after,
        "count": len(items),
        "items": items,
    }
    print_payload(payload)
    return 0


def main() -> int:
    try:
        return asyncio.run(run())
    except MemoryCliError as exc:
        print_payload(
            {
                "ok": False,
                "message": str(exc),
                "error_type": type(exc).__name__,
            }
        )
        return exc.exit_code
    except Exception as exc:
        print_payload(
            {
                "ok": False,
                "message": str(exc),
                "error_type": type(exc).__name__,
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())