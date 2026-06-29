from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.contracts.errors import MemoryAdapterError
from app.contracts.memory import (
    MemoryGetRequest,
    MemoryScope,
    MemorySearchFilters,
    MemorySearchRequest,
)
from app.memory.adapters.memory_store import MemoryStoreAdapter
from app.persistence.settings import MemoryStoreSettings


@pytest.mark.asyncio
async def test_memory_store_adapter_search_maps_scores_and_applies_public_filters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    created_services: list[FakeMemoryService] = []

    class FakeMemorySearchQuery:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

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
        def __init__(self, *, config_path: object, overrides: dict[str, object]) -> None:
            self.config_path = config_path
            self.overrides = overrides
            self.search_calls: list[FakeMemorySearchQuery] = []
            self.closed = False

        @classmethod
        def from_config(
            cls,
            config_path: object = None,
            **overrides: object,
        ) -> FakeMemoryService:
            service = cls(config_path=config_path, overrides=dict(overrides))
            created_services.append(service)
            return service

        def search(self, query: FakeMemorySearchQuery) -> list[object]:
            self.search_calls.append(query)
            matching_record = SimpleNamespace(
                memory_id="memory-1",
                text="Document guidance",
                memory_type="project_fact",
                scope=SimpleNamespace(user_id="user-1", project_id="project-1", agent_id="agent-1"),
                status="active",
                metadata={
                    "topic": "memory",
                    "_backend_source": {"source_id": "source-1", "document_id": "doc-1"},
                },
                source_hash="source-1",
                source_uri="docs/guide.md",
                chunk_id="chunk-1",
                title="Guide",
                summary="summary",
                tags=["keep", "memory"],
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                updated_at=datetime(2026, 1, 2, tzinfo=UTC),
                heading_path=["Guide", "Memory"],
            )
            filtered_record = SimpleNamespace(
                memory_id="memory-2",
                text="Ignore me",
                memory_type="project_fact",
                scope=SimpleNamespace(user_id="user-1", project_id="project-1", agent_id="agent-1"),
                status="removed",
                metadata={
                    "_backend_source": {"source_id": "source-2", "document_id": "doc-2"},
                },
                source_hash="source-2",
                chunk_id=None,
                tags=["drop"],
                created_at=datetime(2025, 1, 1, tzinfo=UTC),
            )
            return [
                SimpleNamespace(
                    memory=matching_record,
                    final_score=0.92,
                    component_scores={"vector": 0.6, "full_text": 0.4, "graph": 0.1},
                    normalized_scores={"vector": 0.9, "full_text": 0.7},
                    debug={"provider": "fake"},
                ),
                SimpleNamespace(
                    memory=filtered_record,
                    final_score=0.3,
                    component_scores={"vector": 0.2},
                    normalized_scores={"vector": 0.2},
                    debug={},
                ),
            ]

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(
        "app.persistence.memory_store_adapter._load_memory_store_runtime",
        lambda: SimpleNamespace(
            MemoryCreate=FakeMemoryCreate,
            MemorySearchQuery=FakeMemorySearchQuery,
            MemoryService=FakeMemoryService,
            Scope=FakeScope,
        ),
    )

    adapter = MemoryStoreAdapter(
        MemoryStoreSettings(
            config_path=None,
            database_path=tmp_path / "memory-store",
            default_scope="project",
            search_limit_default=8,
            search_limit_max=20,
            allow_writes=False,
        ),
        required=False,
    )

    results = await adapter.search(
        MemorySearchRequest(
            text="memory guidance",
            scope=MemoryScope(
                user_id="user-1",
                project_id="project-1",
                agent_name="agent-1",
            ),
            include_document_chunks=False,
            limit=50,
            filters=MemorySearchFilters(
                kinds=("project_fact",),
                tags=("keep",),
                status=("active",),
                source_ids=("source-1",),
                document_ids=("doc-1",),
                created_after="2025-12-31T00:00:00+00:00",
            ),
        )
    )
    await adapter.close()

    assert len(created_services) == 1
    query = created_services[0].search_calls[0]
    assert query.scope.agent_id == "agent-1"
    assert query.limit == 20
    assert query.memory_types == ["project_fact"]
    assert query.statuses == ["active"]
    assert results.search_strategy == "memory_store"
    assert results.total_candidates == 1
    assert len(results.results) == 1
    hit = results.results[0]
    assert hit.memory_id == "memory-1"
    assert hit.record is not None
    assert hit.record.scope.agent_name == "agent-1"
    assert hit.record.scope.document_id == "doc-1"
    assert hit.score == pytest.approx(0.92)
    assert hit.score_details is not None
    assert hit.score_details.component_scores["vector"] == pytest.approx(0.6)
    assert hit.score_details.bm25_score == pytest.approx(0.4)
    assert hit.score_details.graph_score == pytest.approx(0.1)
    assert hit.score_details.normalized_scores["full_text"] == pytest.approx(0.7)
    assert created_services[0].closed is True


@pytest.mark.asyncio
async def test_memory_store_adapter_get_chunk_maps_document_chunk_metadata(
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

    class FakeMemoryService:
        def __init__(self) -> None:
            self.get_chunk_calls: list[tuple[str, FakeScope | None]] = []

        @classmethod
        def from_config(cls, config_path: object = None, **overrides: object) -> FakeMemoryService:
            service = cls()
            created_services.append(service)
            return service

        def get_chunk(self, chunk_id: str, *, scope: FakeScope | None = None) -> object:
            self.get_chunk_calls.append((chunk_id, scope))
            return SimpleNamespace(
                memory_id="memory-chunk-1",
                chunk_id="chunk-1",
                source_path="docs/guide.md",
                source_hash="source-1",
                title="Guide",
                summary="chunk summary",
                text="Chunk body",
                tags=["doc", "memory"],
                heading_path=["Guide", "Section"],
                document_chunk_index=4,
                section_chunk_index=2,
                metadata={
                    "_backend_source": {
                        "source_id": "source-1",
                        "document_id": "doc-1",
                    }
                },
            )

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
            database_path=tmp_path / "memory-store",
            default_scope="project",
            search_limit_default=8,
            search_limit_max=20,
            allow_writes=False,
        ),
        required=False,
    )

    request_scope = MemoryScope(
        user_id="user-1",
        project_id="project-1",
        tenant_id="tenant-1",
        session_id="session-1",
        agent_name="agent-1",
        usecase="chat",
        source_id="source-1",
        document_id="doc-1",
        tags=("tag-1",),
    )
    record = await adapter.get(
        MemoryGetRequest(identifier="chunk-1", scope=request_scope, lookup_kind="chunk")
    )

    assert record is not None
    assert record.memory_type == "document_chunk"
    assert record.scope.agent_name == "agent-1"
    assert record.scope.tenant_id == "tenant-1"
    assert record.source is not None
    assert record.source.chunk_id == "chunk-1"
    assert record.source.source_uri == "docs/guide.md"
    assert record.source.chunk_index == 4
    assert record.source.section_path == ("Guide", "Section")
    assert record.source.document_id == "doc-1"
    assert created_services[0].get_chunk_calls[0][1].agent_id == "agent-1"


@pytest.mark.asyncio
async def test_memory_store_adapter_stats_maps_wrapper_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
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
        def from_config(cls, config_path: object = None, **overrides: object) -> FakeMemoryService:
            return cls()

        def stats(self) -> object:
            return SimpleNamespace(
                total_records=3,
                scope_counts={"global": 1, "scoped": 2},
                status_counts={"active": 2, "superseded": 1},
                type_counts={"project_fact": 2, "document_chunk": 1},
            )

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
            database_path=tmp_path / "memory-store",
            default_scope="project",
            search_limit_default=8,
            search_limit_max=20,
            allow_writes=False,
        ),
        required=False,
    )

    stats = await adapter.stats()

    assert stats.total_records == 3
    assert stats.scope_counts == {"global": 1, "scoped": 2}
    assert stats.status_counts == {"active": 2, "superseded": 1}
    assert stats.type_counts == {"project_fact": 2, "document_chunk": 1}
    assert stats.provider == "memory_store"


@pytest.mark.asyncio
async def test_memory_store_adapter_search_normalizes_wrapper_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
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

    class FakeMemorySearchQuery:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class FakeMemoryService:
        @classmethod
        def from_config(cls, config_path: object = None, **overrides: object) -> FakeMemoryService:
            return cls()

        def search(self, query: FakeMemorySearchQuery) -> list[object]:
            raise RuntimeError("boom")

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "app.persistence.memory_store_adapter._load_memory_store_runtime",
        lambda: SimpleNamespace(
            MemoryCreate=object,
            MemorySearchQuery=FakeMemorySearchQuery,
            MemoryService=FakeMemoryService,
            Scope=FakeScope,
        ),
    )

    adapter = MemoryStoreAdapter(
        MemoryStoreSettings(
            config_path=None,
            database_path=tmp_path / "memory-store",
            default_scope="project",
            search_limit_default=8,
            search_limit_max=20,
            allow_writes=False,
        ),
        required=False,
    )

    with pytest.raises(MemoryAdapterError):
        await adapter.search(
            MemorySearchRequest(
                text="memory guidance",
                scope=MemoryScope(project_id="project-1"),
            )
        )