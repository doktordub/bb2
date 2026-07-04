from __future__ import annotations

import os
from pathlib import Path
import sys
from types import ModuleType
from types import SimpleNamespace

import pytest

from app.contracts.memory import MemoryScope
from app.memory.cli_support import (
    CliScopeResolution,
    MemoryCliError,
    build_document_ingest_request,
    format_cli_scope_summary,
    close_memory_runtime,
    discover_markdown_files,
    load_memory_runtime,
    resolve_cli_scope,
    resolve_docs_directory,
)
from app.testing.fakes import FakeConfigurationView
from tests.unit.memory.support import build_project_scope_config


def test_resolve_docs_directory_rejects_paths_outside_docs_root(tmp_path: Path) -> None:
    docs_root = tmp_path / "repo" / "docs"
    docs_root.mkdir(parents=True)

    with pytest.raises(MemoryCliError, match="within repository docs"):
        resolve_docs_directory("..", docs_root=docs_root)


def test_discover_markdown_files_only_returns_md_files(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs"
    nested = docs_root / "nested"
    nested.mkdir(parents=True)
    (docs_root / "keep.md").write_text("# keep\n", encoding="utf-8")
    (nested / "also-keep.MD").write_text("# keep\n", encoding="utf-8")
    (nested / "skip.markdown").write_text("# skip\n", encoding="utf-8")
    (nested / "skip.txt").write_text("skip\n", encoding="utf-8")

    results = discover_markdown_files(docs_root)

    assert [path.relative_to(docs_root).as_posix() for path in results] == [
        "keep.md",
        "nested/also-keep.MD",
    ]


def test_build_document_ingest_request_uses_repo_relative_identity(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    doc_path = repo_root / "docs" / "plans" / "sample.md"
    doc_path.parent.mkdir(parents=True)
    doc_path.write_text("# sample\n", encoding="utf-8")

    request = build_document_ingest_request(
        doc_path,
        scope=MemoryScope(project_id="docs", agent_name="reviewer"),
        repo_root=repo_root,
    )

    assert request.source_id == "docs/plans/sample.md"
    assert request.document_id == "docs/plans/sample.md"
    assert request.source_uri == "docs/plans/sample.md"
    assert request.path == str(doc_path.resolve(strict=False))
    assert request.scope.project_id == "docs"
    assert request.scope.agent_name == "reviewer"
    assert request.scope.source_id == "docs/plans/sample.md"
    assert request.scope.document_id == "docs/plans/sample.md"
    assert request.metadata["corpus"] == "docs"
    assert request.metadata["repo_relative_path"] == "docs/plans/sample.md"


@pytest.mark.asyncio
async def test_load_memory_runtime_builds_memory_store_adapter_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setenv("MEMORY_STORE_DB_PATH", "E:/temp/backend-memory-store")

    class FakeAdapter:
        def __init__(self, settings: object, *, required: bool) -> None:
            captured["settings"] = settings
            captured["required"] = required

        async def initialize(self) -> None:
            captured["initialized"] = True
            captured["env_visible_during_initialize"] = os.getenv("MEMORY_STORE_DB_PATH")

        async def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr("app.memory.cli_support.MemoryStoreAdapter", FakeAdapter)

    runtime = await load_memory_runtime("config/app.yaml", require_writes=True)

    assert captured["initialized"] is True
    assert captured["required"] is False
    assert captured["env_visible_during_initialize"] is None
    assert runtime.database_path is not None
    assert runtime.search_limit_default == 10
    assert runtime.search_limit_max == 30
    assert runtime.allow_writes is True
    assert os.getenv("MEMORY_STORE_DB_PATH") == "E:/temp/backend-memory-store"

    await close_memory_runtime(runtime)

    assert captured["closed"] is True


def test_shutdown_embedded_memory_jvm_invokes_imported_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, bool] = {"shutdown": False}
    package = ModuleType("arcadedb_embedded")
    jvm_module = ModuleType("arcadedb_embedded.jvm")

    def fake_shutdown_jvm() -> None:
        captured["shutdown"] = True

    jvm_module.shutdown_jvm = fake_shutdown_jvm  # type: ignore[attr-defined]
    package.jvm = jvm_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "arcadedb_embedded", package)
    monkeypatch.setitem(sys.modules, "arcadedb_embedded.jvm", jvm_module)

    from app.memory.cli_support import _shutdown_embedded_memory_jvm

    _shutdown_embedded_memory_jvm()

    assert captured["shutdown"] is True


@pytest.mark.asyncio
async def test_close_memory_runtime_shuts_down_embedded_jvm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, bool] = {"closed": False, "shutdown": False}

    class FakeAdapter:
        async def close(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(
        "app.memory.cli_support._shutdown_embedded_memory_jvm",
        lambda: captured.__setitem__("shutdown", True),
    )

    runtime = SimpleNamespace(adapter=FakeAdapter())

    await close_memory_runtime(runtime)

    assert captured == {"closed": True, "shutdown": True}


def test_resolve_cli_scope_uses_configured_default_and_reports_unset_dimensions() -> None:
    config = FakeConfigurationView(
        build_project_scope_config(
            usecase_name="architecture_document_qa",
            agent_name="architecture_document_agent",
            usecase_allowed_project_ids=("arch_docs",),
            usecase_default_project_id="arch_docs",
            agent_allowed_project_ids=("arch_docs",),
            agent_default_project_id="arch_docs",
        )
    )

    resolution = resolve_cli_scope(
        config,
        project_id="",
        user_id="",
        agent_id="",
    )

    assert resolution.scope.project_id == "arch_docs"
    assert resolution.project_id_resolution == "usecase_default"
    assert format_cli_scope_summary(resolution) == (
        "project_id not provided; using configured default 'arch_docs'.",
        "user_id not provided; scope will remain project-only.",
        "agent_id not provided; no agent-specific memory scope will be applied.",
    )


def test_resolve_cli_scope_rejects_project_outside_configured_allowlist() -> None:
    config = FakeConfigurationView(
        build_project_scope_config(
            usecase_name="architecture_document_qa",
            agent_name="architecture_document_agent",
            usecase_allowed_project_ids=("arch_docs",),
            agent_allowed_project_ids=("arch_docs",),
        )
    )

    with pytest.raises(MemoryCliError, match="not allowed"):
        resolve_cli_scope(
            config,
            project_id="docs",
            user_id="",
            agent_id="",
        )