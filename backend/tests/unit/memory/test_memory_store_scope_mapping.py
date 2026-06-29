from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.contracts.memory import MemoryScope, MemorySource, MemoryWrite
from app.memory.adapters.memory_store import MemoryStoreAdapter, normalize_memory_search_limit
from app.persistence.settings import MemoryStoreSettings


def test_memory_scope_normalizes_strings_and_summarizes_without_identifiers() -> None:
    scope = MemoryScope(
        user_id=" user-1 ",
        project_id=" ",
        tenant_id=" tenant-1 ",
        session_id=" session-1 ",
        metadata={"kind": "test"},
    )

    normalized = scope.normalized()

    assert normalized.user_id == "user-1"
    assert normalized.project_id is None
    assert normalized.tenant_id == "tenant-1"
    assert normalized.session_id == "session-1"
    assert normalized.has_explicit_scope() is True
    assert normalized.summary() == {
        "scope_type": "user",
        "user_id_present": True,
        "project_id_present": False,
        "tenant_id_present": True,
        "session_id_present": True,
        "agent_name_present": False,
        "usecase_present": False,
        "source_id_present": False,
        "document_id_present": False,
        "tag_count": 0,
    }


def test_normalize_memory_search_limit_uses_defaults_and_caps_maximum() -> None:
    assert normalize_memory_search_limit(None, default_limit=8, max_limit=20) == 8
    assert normalize_memory_search_limit(0, default_limit=8, max_limit=20) == 8
    assert normalize_memory_search_limit(50, default_limit=8, max_limit=20) == 20
    assert normalize_memory_search_limit(3, default_limit=8, max_limit=20) == 3


@pytest.mark.asyncio
async def test_memory_store_adapter_upsert_maps_backend_scope_and_source_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
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

    class FakeMemoryCreate:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class FakeMemoryService:
        def __init__(self) -> None:
            self.upsert_calls: list[tuple[FakeMemoryCreate, str | None, bool]] = []

        @classmethod
        def from_config(cls, config_path: object = None, **overrides: object) -> FakeMemoryService:
            service = cls()
            created_services.append(service)
            return service

        def upsert_memory(
            self,
            memory: FakeMemoryCreate,
            stable_key: str | None = None,
            *,
            embed: bool = False,
        ) -> object:
            self.upsert_calls.append((memory, stable_key, embed))
            return SimpleNamespace(
                memory_id="memory-1",
                text=memory.text,
                memory_type=memory.memory_type,
                scope=memory.scope,
                metadata=memory.metadata,
                source_hash=memory.source_hash,
                source_uri=memory.source_uri,
                chunk_id=memory.chunk_id,
                title=memory.title,
                tags=memory.tags,
                confidence=memory.confidence,
                importance=memory.importance,
                heading_path=memory.heading_path,
                document_chunk_index=memory.document_chunk_index,
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.persistence.memory_store_adapter._load_memory_store_runtime",
        lambda: SimpleNamespace(
            MemoryCreate=FakeMemoryCreate,
            MemorySearchQuery=object,
            MemoryService=FakeMemoryService,
            Scope=FakeScope,
        ),
    )

    adapter = MemoryStoreAdapter(
        MemoryStoreSettings(
            config_path=None,
            database_path=tmp_path / "memory-store",
            default_scope="user",
            search_limit_default=10,
            search_limit_max=30,
            allow_writes=True,
        ),
        required=False,
    )

    result = await adapter.upsert(
        MemoryWrite(
            text="Remember this",
            scope=MemoryScope(
                user_id="user-1",
                project_id="project-1",
                tenant_id="tenant-1",
                session_id="session-1",
                agent_name="agent-1",
                usecase="chat",
                source_id="source-1",
                document_id="doc-1",
                tags=("scope-tag",),
                metadata={"scope_kind": "project_user"},
            ),
            memory_type="project_fact",
            stable_key="fact-1",
            source=MemorySource(
                source_id="source-1",
                document_id="doc-1",
                source_uri="docs/guide.md",
                source_hash="hash-1",
                chunk_id="chunk-1",
                chunk_index=3,
                section_path=("Guide", "Memory"),
                title="Guide",
                metadata={"origin": "fixture"},
            ),
            metadata={"topic": "memory"},
        )
    )

    assert len(created_services) == 1
    created_memory, stable_key, embed = created_services[0].upsert_calls[0]
    assert created_memory.scope.user_id == "user-1"
    assert created_memory.scope.project_id == "project-1"
    assert created_memory.scope.agent_id == "agent-1"
    assert stable_key == "fact-1"
    assert embed is False
    assert created_memory.document_chunk_index == 3
    assert created_memory.metadata["topic"] == "memory"
    assert created_memory.metadata["_backend_scope"] == {
        "user_id": "user-1",
        "project_id": "project-1",
        "tenant_id": "tenant-1",
        "session_id": "session-1",
        "agent_name": "agent-1",
        "usecase": "chat",
        "source_id": "source-1",
        "document_id": "doc-1",
        "tags": ["scope-tag"],
        "metadata": {"scope_kind": "project_user"},
    }
    assert created_memory.metadata["_backend_source"] == {
        "source_id": "source-1",
        "document_id": "doc-1",
        "chunk_index": 3,
        "metadata": {"origin": "fixture"},
    }
    assert result.record is not None
    assert result.record.scope.tenant_id == "tenant-1"
    assert result.record.scope.session_id == "session-1"
    assert result.record.scope.document_id == "doc-1"
    assert result.record.scope.source_id == "source-1"
    assert result.record.scope.tags == ("scope-tag",)
    assert result.record.source is not None
    assert result.record.source.document_id == "doc-1"
    assert result.record.source.chunk_index == 3
    assert result.record.source.metadata == {"origin": "fixture"}
    assert result.record.metadata == {"topic": "memory"}