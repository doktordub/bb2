from __future__ import annotations

from app.contracts.memory import (
    DocumentIngestRequest,
    MemoryDeleteByScopeRequest,
    MemoryExportByScopeRequest,
    MemoryForgetRequest,
    MemoryGetRequest,
    MemoryLifecycleRequest,
    MemoryResult,
    MemoryScope,
    MemorySearchRequest,
    MemorySupersedeRequest,
    MemoryContradictRequest,
    MemoryWrite,
)
from app.memory.adapters.fake import FakeMemoryAdapter


def build_scope() -> MemoryScope:
    return MemoryScope(user_id="user-1", project_id="project-1", session_id="session-1")


async def test_fake_memory_adapter_is_deterministic_for_search_write_lookup_and_forget() -> None:
    adapter = FakeMemoryAdapter(
        results=[MemoryResult(memory_id="memory-1", text="remember this", memory_type="note")]
    )
    scope = build_scope()
    search_request = MemorySearchRequest(text="remember", scope=scope, query_id="query-1")
    write_request = MemoryWrite(
        text="remember this",
        scope=scope,
        memory_type="note",
        stable_key="note-1",
    )

    await adapter.initialize()
    search_result = await adapter.search(search_request)
    write_result = await adapter.upsert(write_request)
    fetched = await adapter.get(MemoryGetRequest(identifier="note-1", scope=scope))
    forget_result = await adapter.forget(MemoryForgetRequest(memory_id="note-1", scope=scope))
    stats = await adapter.stats()
    health = await adapter.health()
    await adapter.close()

    assert search_result.results == [
        MemoryResult(memory_id="memory-1", text="remember this", memory_type="note")
    ]
    assert adapter.search_requests == [search_request]
    assert adapter.writes == [write_request]
    assert write_result.record is not None
    assert write_result.record.memory_id == "note-1"
    assert fetched is not None
    assert fetched.memory_id == "note-1"
    assert forget_result.status == "forgotten"
    assert stats.total_records == 0
    assert health.provider == "fake"
    assert adapter.initialize_calls == 1
    assert adapter.close_calls == 1


async def test_fake_memory_adapter_tracks_lifecycle_ingest_and_privacy_operations() -> None:
    adapter = FakeMemoryAdapter()
    scope = build_scope()

    await adapter.upsert(
        MemoryWrite(
            text="old memory",
            scope=scope,
            memory_type="fact",
            stable_key="old-memory",
        )
    )
    await adapter.upsert(
        MemoryWrite(
            text="new memory",
            scope=scope,
            memory_type="fact",
            stable_key="new-memory",
        )
    )

    promote_result = await adapter.promote(
        MemoryLifecycleRequest(memory_id="old-memory", scope=scope, reason="promote")
    )
    supersede_result = await adapter.supersede(
        MemorySupersedeRequest(
            old_memory_id="old-memory",
            new_memory_id="new-memory",
            scope=scope,
            reason="replace",
        )
    )
    contradict_result = await adapter.contradict(
        MemoryContradictRequest(
            memory_id_a="old-memory",
            memory_id_b="new-memory",
            scope=scope,
            reason="conflict",
        )
    )
    ingest_result = await adapter.ingest_document(
        DocumentIngestRequest(
            source_id="source-1",
            document_id="doc-1",
            scope=scope,
            content="# Title\n\nBody",
        )
    )
    export_result = await adapter.export_by_scope(
        MemoryExportByScopeRequest(scope=scope, include_content=True)
    )
    delete_result = await adapter.delete_by_scope(
        MemoryDeleteByScopeRequest(scope=scope, hard_delete=False)
    )

    assert promote_result.operation == "promote"
    assert supersede_result.affected_ids == ("old-memory", "new-memory")
    assert contradict_result.affected_ids == ("old-memory", "new-memory")
    assert ingest_result.chunks_created == 1
    assert export_result.record_count == 2
    assert delete_result.deleted_count == 2
    assert len(adapter.lifecycle_requests) == 1
    assert len(adapter.supersede_requests) == 1
    assert len(adapter.contradict_requests) == 1
    assert len(adapter.ingest_requests) == 1
    assert len(adapter.export_requests) == 1
    assert len(adapter.delete_requests) == 1