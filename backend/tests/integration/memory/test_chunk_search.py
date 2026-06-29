from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.contracts.memory import MemoryChunkContextRequest, MemoryScope, MemorySearchFilters, MemorySearchRequest
from tests.integration.memory.support import build_context, build_gateway, load_config_view


@pytest.mark.asyncio
async def test_chunk_only_search_and_chunk_context_flow_through_gateway(
    monkeypatch: pytest.MonkeyPatch,
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

    def build_record(memory_id: str, chunk_id: str, text: str, index: int) -> object:
        return SimpleNamespace(
            memory_id=memory_id,
            text=text,
            memory_type="document_chunk",
            scope=SimpleNamespace(user_id="user-1", project_id="project-1", agent_id="support_agent"),
            status="active",
            metadata={
                "_backend_source": {
                    "source_id": "source-1",
                    "document_id": "doc-1",
                    "chunk_index": index,
                }
            },
            source_hash="source-1",
            source_uri="docs/backend_sample.md",
            chunk_id=chunk_id,
            title="Backend Sample",
            summary="sample chunk",
            tags=["memory", "doc"],
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 2, tzinfo=UTC),
            heading_path=["Backend Sample", "Memory"],
            document_chunk_index=index,
        )

    def build_chunk(memory_id: str, chunk_id: str, text: str, index: int) -> object:
        return SimpleNamespace(
            memory_id=memory_id,
            chunk_id=chunk_id,
            source_path="docs/backend_sample.md",
            source_hash="source-1",
            title="Backend Sample",
            summary="sample chunk",
            text=text,
            tags=["memory", "doc"],
            heading_path=["Backend Sample", "Memory"],
            document_chunk_index=index,
            metadata={
                "_backend_source": {
                    "source_id": "source-1",
                    "document_id": "doc-1",
                    "chunk_index": index,
                }
            },
        )

    class FakeMemorySearchQuery:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class FakeMemoryService:
        def __init__(self) -> None:
            self.search_calls: list[FakeMemorySearchQuery] = []
            self.chunk_context_calls: list[tuple[str, FakeScope | None, int, int]] = []

        @classmethod
        def from_config(
            cls,
            config_path: object = None,
            **overrides: object,
        ) -> FakeMemoryService:
            service = cls()
            created_services.append(service)
            return service

        def search(self, query: FakeMemorySearchQuery) -> list[object]:
            self.search_calls.append(query)
            return [
                SimpleNamespace(
                    memory=build_record(
                        "memory-2",
                        "chunk-2",
                        "MemoryGateway provides chunk-oriented retrieval.",
                        2,
                    ),
                    final_score=0.94,
                    component_scores={"vector": 0.7},
                    normalized_scores={"vector": 0.9},
                    debug={},
                )
            ]

        def get_chunk_context(
            self,
            chunk_id: str,
            *,
            scope: FakeScope | None = None,
            before: int = 0,
            after: int = 0,
        ) -> object:
            self.chunk_context_calls.append((chunk_id, scope, before, after))
            return SimpleNamespace(
                chunk=build_chunk("memory-2", "chunk-2", "MemoryGateway provides chunk-oriented retrieval.", 2),
                before=[build_chunk("memory-1", "chunk-1", "Before context.", 1)],
                after=[build_chunk("memory-3", "chunk-3", "After context.", 3)],
            )

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

    config = await load_config_view("memory_store_markdown_chunking.yaml", env={})
    gateway = await build_gateway(config)
    context = build_context(config)

    search_result = await gateway.search(
        MemorySearchRequest(
            text="memory gateway",
            scope=MemoryScope(project_id="project-1"),
            filters=MemorySearchFilters(kinds=("document_chunk",), status=("active",)),
            include_document_chunks=True,
            limit=4,
        ),
        context,
    )
    chunk_context = await gateway.get_chunk_context(
        MemoryChunkContextRequest(
            chunk_id="chunk-2",
            scope=MemoryScope(project_id="project-1"),
            before=1,
            after=1,
        ),
        context,
    )

    assert [result.chunk_id for result in search_result.results] == ["chunk-2"]
    assert created_services[0].search_calls[0].memory_types == ["document_chunk"]
    assert chunk_context is not None
    assert [item.chunk_id for item in chunk_context.before] == ["chunk-1"]
    assert [item.chunk_id for item in chunk_context.after] == ["chunk-3"]
    assert created_services[0].chunk_context_calls[0][2:] == (1, 1)

    if hasattr(gateway, "close"):
        await gateway.close()