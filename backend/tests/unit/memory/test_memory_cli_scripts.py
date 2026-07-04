from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from app.contracts.memory import MemoryScope
from app.memory.cli_support import CliScopeResolution
from app.testing.fakes import FakeConfigurationView


SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"


def _load_script_module(script_name: str) -> ModuleType:
    script_path = SCRIPTS_DIR / script_name
    module_name = f"test_{script_path.stem}_{abs(hash(script_path))}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_markdown_ingest_cli_emits_json_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module("markdown_folder_ingest_cli.py")
    docs_root = tmp_path / "docs"
    file_a = docs_root / "alpha.md"
    file_b = docs_root / "nested" / "beta.md"
    file_b.parent.mkdir(parents=True)
    file_a.write_text("# Alpha\n", encoding="utf-8")
    file_b.write_text("# Beta\n", encoding="utf-8")
    closed: dict[str, bool] = {"value": False}

    class FakeAdapter:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def ingest_document(self, request: object) -> object:
            self.requests.append(request)
            created = 1 if str(getattr(request, "source_id", "")).endswith("alpha.md") else 2
            return SimpleNamespace(
                chunks_created=created,
                chunks_updated=0,
                chunks_removed=0,
                chunks_unchanged=0,
            )

    runtime = SimpleNamespace(
        adapter=FakeAdapter(),
        database_path=tmp_path / "memory-store",
        config=FakeConfigurationView({}),
    )
    scope_resolution = CliScopeResolution(
        scope=MemoryScope(project_id="arch_docs"),
        requested_scope=MemoryScope(),
        project_id_resolution="usecase_default",
        user_id_resolution="unset",
        agent_id_resolution="unset",
    )

    async def fake_load_memory_runtime(*args: object, **kwargs: object) -> object:
        return runtime

    async def fake_close_memory_runtime(runtime_arg: object) -> None:
        assert runtime_arg is runtime
        closed["value"] = True

    def fake_build_document_ingest_request(path: Path, *, scope: object) -> object:
        repo_path = path.relative_to(docs_root).as_posix()
        return SimpleNamespace(
            source_uri=f"docs/{repo_path}",
            source_id=f"docs/{repo_path}",
            document_id=f"docs/{repo_path}",
            scope=scope,
        )

    monkeypatch.setattr(module, "parse_args", lambda: SimpleNamespace(
        docs_subpath=None,
        config_path=Path("config/app.yaml"),
        user_id="",
        project_id="docs",
        agent_id="",
        fail_fast=False,
    ))
    monkeypatch.setattr(module, "load_memory_runtime", fake_load_memory_runtime)
    monkeypatch.setattr(module, "close_memory_runtime", fake_close_memory_runtime)
    monkeypatch.setattr(module, "resolve_cli_scope", lambda *args, **kwargs: scope_resolution)
    monkeypatch.setattr(module, "resolve_docs_directory", lambda subpath: docs_root)
    monkeypatch.setattr(module, "discover_markdown_files", lambda root: [file_a, file_b])
    monkeypatch.setattr(module, "build_document_ingest_request", fake_build_document_ingest_request)

    exit_code = await module.run()

    assert exit_code == 0
    assert closed["value"] is True
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "project_id not provided; using configured default 'arch_docs'." in captured.err
    assert "user_id not provided; scope will remain project-only." in captured.err
    assert "agent_id not provided; no agent-specific memory scope will be applied." in captured.err
    assert "Closing memory runtime..." in captured.err
    assert payload == {
        "ok": True,
        "message": "Processed 2 Markdown file(s).",
        "docs_root": str(docs_root),
        "database_path": str((tmp_path / "memory-store").resolve(strict=False)),
        "scope": {
            "user_id": "",
            "project_id": "arch_docs",
            "agent_id": "",
        },
        "requested_scope": {
            "user_id": "",
            "project_id": "docs",
            "agent_id": "",
        },
        "scope_resolution": {
            "project_id": "usecase_default",
            "user_id": "unset",
            "agent_id": "unset",
        },
        "matched_files": 2,
        "processed_files": 2,
        "failed_files": 0,
        "totals": {
            "added": 3,
            "updated": 0,
            "removed": 0,
            "unchanged": 0,
        },
        "files": [
            {
                "path": "docs/alpha.md",
                "source_id": "docs/alpha.md",
                "document_id": "docs/alpha.md",
                "source_uri": "docs/alpha.md",
                "added": 1,
                "updated": 0,
                "removed": 0,
                "unchanged": 0,
            },
            {
                "path": "docs/nested/beta.md",
                "source_id": "docs/nested/beta.md",
                "document_id": "docs/nested/beta.md",
                "source_uri": "docs/nested/beta.md",
                "added": 2,
                "updated": 0,
                "removed": 0,
                "unchanged": 0,
            },
        ],
        "failures": [],
    }


@pytest.mark.asyncio
async def test_chunk_search_cli_emits_json_results_with_optional_context(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    module = _load_script_module("chunk_search_cli.py")
    closed: dict[str, bool] = {"value": False}
    captured: dict[str, object] = {}

    def build_source(*, index: int) -> object:
        return SimpleNamespace(
            source_uri="docs/backend-guide.md",
            source_id="docs/backend-guide.md",
            document_id="docs/backend-guide.md",
            chunk_index=index,
            section_path=("Backend Guide", "Memory"),
        )

    def build_result(*, memory_id: str, chunk_id: str, text: str, index: int) -> object:
        return SimpleNamespace(
            memory_id=memory_id,
            chunk_id=chunk_id,
            score=0.91,
            score_details=SimpleNamespace(
                final_score=0.9123,
                component_scores={"vector": 0.7, "reranker": 0.95},
            ),
            record=SimpleNamespace(
                chunk_id=chunk_id,
                title="Backend Guide",
                summary="",
                text=text,
                source=build_source(index=index),
            ),
        )

    class FakeAdapter:
        async def search(self, request: object) -> object:
            captured["search_request"] = request
            return SimpleNamespace(
                results=[
                    build_result(
                        memory_id="memory-1",
                        chunk_id="chunk-2",
                        text="Memory gateway search returns document chunks.",
                        index=2,
                    )
                ]
            )

        async def get_chunk_context(self, request: object) -> object:
            captured["context_request"] = request
            return SimpleNamespace(
                before=[
                    build_result(
                        memory_id="memory-0",
                        chunk_id="chunk-1",
                        text="Context before.",
                        index=1,
                    )
                ],
                after=[
                    build_result(
                        memory_id="memory-2",
                        chunk_id="chunk-3",
                        text="Context after.",
                        index=3,
                    )
                ],
            )

    runtime = SimpleNamespace(
        adapter=FakeAdapter(),
        database_path=tmp_path / "memory-store",
        config=FakeConfigurationView({}),
        search_limit_default=10,
        search_limit_max=30,
    )
    scope_resolution = CliScopeResolution(
        scope=MemoryScope(project_id="arch_docs"),
        requested_scope=MemoryScope(),
        project_id_resolution="usecase_default",
        user_id_resolution="unset",
        agent_id_resolution="unset",
    )

    async def fake_load_memory_runtime(*args: object, **kwargs: object) -> object:
        return runtime

    async def fake_close_memory_runtime(runtime_arg: object) -> None:
        assert runtime_arg is runtime
        closed["value"] = True

    monkeypatch.setattr(module, "parse_args", lambda: SimpleNamespace(
        query="memory gateway",
        config_path=Path("config/app.yaml"),
        user_id="",
        project_id="docs",
        agent_id="",
        limit=5,
        before=1,
        after=1,
    ))
    monkeypatch.setattr(module, "load_memory_runtime", fake_load_memory_runtime)
    monkeypatch.setattr(module, "close_memory_runtime", fake_close_memory_runtime)
    monkeypatch.setattr(module, "resolve_cli_scope", lambda *args, **kwargs: scope_resolution)

    exit_code = await module.run()

    assert exit_code == 0
    assert closed["value"] is True
    search_request = captured["search_request"]
    assert search_request.limit == 5
    assert search_request.include_document_chunks is True
    assert search_request.filters.kinds == ("document_chunk",)
    assert search_request.filters.status == ("active",)
    context_request = captured["context_request"]
    assert context_request.chunk_id == "chunk-2"
    assert context_request.before == 1
    assert context_request.after == 1

    captured = capsys.readouterr()
    assert "project_id not provided; using configured default 'arch_docs'." in captured.err
    assert "user_id not provided; scope will remain project-only." in captured.err
    assert "agent_id not provided; no agent-specific memory scope will be applied." in captured.err
    payload = json.loads(captured.out)
    assert payload == {
        "ok": True,
        "message": "Found 1 chunk result(s).",
        "query": "memory gateway",
        "database_path": str((tmp_path / "memory-store").resolve(strict=False)),
        "scope": {
            "user_id": "",
            "project_id": "arch_docs",
            "agent_id": "",
        },
        "requested_scope": {
            "user_id": "",
            "project_id": "docs",
            "agent_id": "",
        },
        "scope_resolution": {
            "project_id": "usecase_default",
            "user_id": "unset",
            "agent_id": "unset",
        },
        "limit": 5,
        "limit_max": 30,
        "before": 1,
        "after": 1,
        "count": 1,
        "items": [
            {
                "memory_id": "memory-1",
                "chunk_id": "chunk-2",
                "title": "Backend Guide",
                "summary": "",
                "text": "Memory gateway search returns document chunks.",
                "snippet": "Memory gateway search returns document chunks.",
                "source_uri": "docs/backend-guide.md",
                "source_id": "docs/backend-guide.md",
                "document_id": "docs/backend-guide.md",
                "heading_path": ["Backend Guide", "Memory"],
                "heading_path_label": "Backend Guide / Memory",
                "document_chunk_index": 2,
                "score": 0.9123,
                "score_label": "0.912",
                "component_scores": {"vector": 0.7, "reranker": 0.95},
                "context": {
                    "before": [
                        {
                            "memory_id": "memory-0",
                            "chunk_id": "chunk-1",
                            "title": "Backend Guide",
                            "source_uri": "docs/backend-guide.md",
                            "document_chunk_index": 1,
                            "text": "Context before.",
                        }
                    ],
                    "after": [
                        {
                            "memory_id": "memory-2",
                            "chunk_id": "chunk-3",
                            "title": "Backend Guide",
                            "source_uri": "docs/backend-guide.md",
                            "document_chunk_index": 3,
                            "text": "Context after.",
                        }
                    ],
                },
            }
        ],
    }