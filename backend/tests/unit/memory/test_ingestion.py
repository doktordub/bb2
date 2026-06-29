from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.contracts.memory import DocumentIngestRequest, MemoryScope
from app.memory.adapters.memory_store import MemoryStoreAdapter
from app.persistence.settings import MemoryStoreSettings


@pytest.mark.asyncio
async def test_memory_store_adapter_ingest_document_accepts_inline_markdown_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    created_services: list[FakeMemoryService] = []

    class FakeScope:
        def __init__(
            self,
            *,
            user_id: str | None = None,
            project_id: str | None = None,
            agent_id: str | None = None,
        ) -> None:
            self.user_id = user_id
            self.project_id = project_id
            self.agent_id = agent_id

    class FakeMemoryService:
        def __init__(self) -> None:
            self.ingest_calls: list[tuple[Path, FakeScope, str]] = []

        @classmethod
        def from_config(
            cls,
            config_path: object = None,
            **overrides: object,
        ) -> FakeMemoryService:
            service = cls()
            created_services.append(service)
            return service

        def ingest_document(self, path: str | Path, scope: FakeScope) -> object:
            resolved_path = Path(path)
            self.ingest_calls.append((resolved_path, scope, resolved_path.read_text(encoding="utf-8")))
            return SimpleNamespace(path=resolved_path, added=2, updated=1, unchanged=0, removed=0)

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.persistence.memory_store_adapter._load_memory_store_runtime",
        lambda: SimpleNamespace(
            MemoryCreate=object,
            MemorySearchQuery=object,
            MemoryService=FakeMemoryService,
            Scope=FakeScope,
        ),
    )

    adapter = MemoryStoreAdapter(
        MemoryStoreSettings(
            config_path=None,
            database_path=tmp_path / "memory-store" / "arcadedb",
            default_scope="project",
            search_limit_default=8,
            search_limit_max=20,
            allow_writes=False,
        ),
        required=False,
    )

    request = DocumentIngestRequest(
        source_id="source-1",
        document_id="doc-1",
        scope=MemoryScope(user_id="user-1", project_id="project-1", agent_name="agent-1"),
        content="# Title\n\nBody text",
        source_hash="source-hash-1",
    )

    result = await adapter.ingest_document(request)

    assert result.chunks_created == 2
    assert result.chunks_updated == 1
    assert result.chunks_unchanged == 0
    assert result.skipped_unchanged_document is False
    assert len(created_services) == 1
    ingest_path, scope, content = created_services[0].ingest_calls[0]
    assert ingest_path.suffix == ".md"
    assert ingest_path.exists() is False
    assert scope.project_id == "project-1"
    assert scope.agent_id == "agent-1"
    assert content == "# Title\n\nBody text"
    assert str(result.metadata["path"]).endswith(".md")


@pytest.mark.asyncio
async def test_memory_store_adapter_ingest_document_marks_unchanged_documents(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeScope:
        def __init__(
            self,
            *,
            user_id: str | None = None,
            project_id: str | None = None,
            agent_id: str | None = None,
        ) -> None:
            self.user_id = user_id
            self.project_id = project_id
            self.agent_id = agent_id

    class FakeMemoryService:
        @classmethod
        def from_config(
            cls,
            config_path: object = None,
            **overrides: object,
        ) -> FakeMemoryService:
            return cls()

        def ingest_document(self, path: str | Path, scope: FakeScope) -> object:
            return SimpleNamespace(path=Path(path), added=0, updated=0, unchanged=3, removed=1)

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.persistence.memory_store_adapter._load_memory_store_runtime",
        lambda: SimpleNamespace(
            MemoryCreate=object,
            MemorySearchQuery=object,
            MemoryService=FakeMemoryService,
            Scope=FakeScope,
        ),
    )

    adapter = MemoryStoreAdapter(
        MemoryStoreSettings(
            config_path=None,
            database_path=tmp_path / "memory-store" / "arcadedb",
            default_scope="project",
            search_limit_default=8,
            search_limit_max=20,
            allow_writes=False,
        ),
        required=False,
    )

    result = await adapter.ingest_document(
        DocumentIngestRequest(
            source_id="source-1",
            document_id="doc-1",
            scope=MemoryScope(project_id="project-1"),
            content="# Title\n\nUnchanged body",
        )
    )

    assert result.chunks_created == 0
    assert result.chunks_updated == 0
    assert result.chunks_unchanged == 3
    assert result.chunks_removed == 1
    assert result.skipped_unchanged_document is True