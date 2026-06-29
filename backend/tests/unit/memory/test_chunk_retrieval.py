from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.contracts.memory import (
    MemoryChunkContextRequest,
    MemoryRecord,
    MemoryScope,
    MemorySource,
)
from app.memory.adapters.fake import FakeMemoryAdapter
from app.memory.adapters.memory_store import MemoryStoreAdapter
from app.persistence.settings import MemoryStoreSettings
from tests.unit.memory.support import build_context, build_gateway


@pytest.mark.asyncio
async def test_memory_store_adapter_get_chunk_context_maps_wrapper_window(
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

    def build_chunk(memory_id: str, chunk_id: str, text: str, index: int) -> object:
        return SimpleNamespace(
            memory_id=memory_id,
            chunk_id=chunk_id,
            source_path="docs/guide.md",
            source_hash="source-1",
            title="Guide",
            summary="chunk summary",
            text=text,
            tags=["doc", "memory"],
            heading_path=["Guide", "Memory"],
            document_chunk_index=index,
            metadata={
                "_backend_source": {
                    "source_id": "source-1",
                    "document_id": "doc-1",
                    "chunk_index": index,
                }
            },
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        )

    class FakeMemoryService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, FakeScope | None, int, int]] = []

        @classmethod
        def from_config(
            cls,
            config_path: object = None,
            **overrides: object,
        ) -> FakeMemoryService:
            service = cls()
            created_services.append(service)
            return service

        def get_chunk_context(
            self,
            chunk_id: str,
            *,
            scope: FakeScope | None = None,
            before: int = 0,
            after: int = 0,
        ) -> object:
            self.calls.append((chunk_id, scope, before, after))
            return SimpleNamespace(
                chunk=build_chunk("memory-2", "chunk-2", "Target chunk", 2),
                before=[build_chunk("memory-1", "chunk-1", "Before chunk", 1)],
                after=[build_chunk("memory-3", "chunk-3", "After chunk", 3)],
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
    )
    result = await adapter.get_chunk_context(
        MemoryChunkContextRequest(
            chunk_id="chunk-2",
            scope=request_scope,
            before=1,
            after=1,
        )
    )

    assert result is not None
    assert result.chunk.chunk_id == "chunk-2"
    assert [item.chunk_id for item in result.before] == ["chunk-1"]
    assert [item.chunk_id for item in result.after] == ["chunk-3"]
    assert result.chunk.record is not None
    assert result.chunk.record.scope.agent_name == "agent-1"
    assert result.chunk.record.scope.tenant_id == "tenant-1"
    assert result.chunk.record.source is not None
    assert result.chunk.record.source.section_path == ("Guide", "Memory")
    assert created_services[0].calls[0][1].agent_id == "agent-1"


@pytest.mark.asyncio
async def test_gateway_get_chunk_context_bounds_chunk_window_text() -> None:
    adapter = FakeMemoryAdapter()
    scope = MemoryScope(user_id="user-1", project_id="project-1")
    adapter.records = {
        "memory-1": MemoryRecord(
            memory_id="memory-1",
            text="Before chunk body with too much detail",
            memory_type="document_chunk",
            scope=scope,
            source=MemorySource(source_id="source-1", chunk_id="chunk-1", chunk_index=1),
        ),
        "memory-2": MemoryRecord(
            memory_id="memory-2",
            text="Target chunk body with too much detail",
            memory_type="document_chunk",
            scope=scope,
            source=MemorySource(source_id="source-1", chunk_id="chunk-2", chunk_index=2),
        ),
        "memory-3": MemoryRecord(
            memory_id="memory-3",
            text="After chunk body with too much detail",
            memory_type="document_chunk",
            scope=scope,
            source=MemorySource(source_id="source-1", chunk_id="chunk-3", chunk_index=3),
        ),
    }
    gateway = build_gateway(adapter=adapter, max_result_chars=12)
    context = build_context()

    result = await gateway.get_chunk_context(
        MemoryChunkContextRequest(
            chunk_id="chunk-2",
            scope=MemoryScope(session_id="session-1"),
            before=1,
            after=1,
        ),
        context,
    )

    assert result is not None
    assert result.chunk.text == "Target ch..."
    assert result.before[0].text == "Before ch..."
    assert result.after[0].text == "After chu..."
    assert adapter.chunk_context_requests[0].scope.project_id == "project-1"
