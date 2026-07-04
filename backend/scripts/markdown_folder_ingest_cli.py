"""CLI utility to ingest repository docs Markdown into backend-configured memory."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
from contextlib import chdir
import json
from pathlib import Path
import sys
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.memory.cli_support import (
    DEFAULT_CONFIG_PATH,
    REPO_ROOT,
    MemoryCliError,
    build_document_ingest_request,
    cli_scope_payload,
    cli_scope_resolution_payload,
    close_memory_runtime,
    discover_markdown_files,
    format_cli_scope_summary,
    load_memory_runtime,
    resolve_cli_scope,
    resolve_docs_directory,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest repository docs Markdown into the backend-configured memory store."
    )
    parser.add_argument(
        "docs_subpath",
        nargs="?",
        default=None,
        help="Optional subdirectory under repository docs/ to ingest.",
    )
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
        "--fail-fast",
        action="store_true",
        help="Stop at the first ingestion failure.",
    )
    return parser.parse_args()


def build_file_result(request: Any, result: Any) -> dict[str, Any]:
    return {
        "path": request.source_uri,
        "source_id": request.source_id,
        "document_id": request.document_id,
        "source_uri": request.source_uri,
        "added": result.chunks_created,
        "updated": result.chunks_updated,
        "removed": result.chunks_removed,
        "unchanged": result.chunks_unchanged,
    }


def print_payload(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2))


def print_progress(message: str) -> None:
    print(message, file=sys.stderr)


async def run() -> int:
    args = parse_args()
    runtime = await load_memory_runtime(args.config_path, require_writes=True)
    scope_resolution = resolve_cli_scope(
        runtime.config,
        project_id=args.project_id,
        user_id=args.user_id,
        agent_id=args.agent_id,
    )
    docs_directory = resolve_docs_directory(args.docs_subpath)
    markdown_files = discover_markdown_files(docs_directory)
    scope = scope_resolution.scope
    totals = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0}
    files: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    try:
        with chdir(REPO_ROOT):
            for line in format_cli_scope_summary(scope_resolution):
                print_progress(line)
            print_progress(
                f"\n\nDiscovered {len(markdown_files)} Markdown file(s) in {docs_directory}..."
            )
            for path in markdown_files:
                request = build_document_ingest_request(path, scope=scope)
                print_progress(
                    f"Ingesting {request.source_uri} (source_id={request.source_id})..."
                )
                try:
                    result = await runtime.adapter.ingest_document(request)
                except Exception as exc:
                    failures.append(
                        {
                            "path": request.source_uri or request.source_id,
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                        }
                    )
                    if args.fail_fast:
                        break
                    continue

                file_result = build_file_result(request, result)
                files.append(file_result)
                for key in totals:
                    totals[key] += int(file_result[key])
    finally:
        print_progress(f"Processed {len(files)} Markdown file(s) with {len(failures)} failure(s).")
        print_progress("Closing memory runtime...")
        await close_memory_runtime(runtime)

    payload = {
        "ok": not failures,
        "message": f"Processed {len(markdown_files)} Markdown file(s).",
        "docs_root": str(docs_directory),
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
        "matched_files": len(markdown_files),
        "processed_files": len(files),
        "failed_files": len(failures),
        "totals": totals,
        "files": files,
        "failures": failures,
    }
    print_payload(payload)
    return 0 if not failures else 1


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