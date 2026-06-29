from app.contracts.errors import (
    MemoryAdapterError,
    MemoryDisabledError,
    MemoryGatewayError,
    MemoryIngestionError,
    MemoryInvalidScopeError,
    MemoryNotFoundError,
    MemoryPolicyDeniedError,
    MemoryPrivacyError,
)
from app.contracts.memory import (
    DocumentIngestRequest,
    MemoryDeleteByScopeRequest,
    MemoryExportByScopeRequest,
    MemoryExportResult,
    MemoryForgetRequest,
    MemoryHealthResult,
    MemoryLifecycleRequest,
    MemoryRecord,
    MemoryResult,
    MemoryScore,
    MemoryScope,
    MemorySearchRequest,
    MemorySearchResult,
    MemorySource,
    MemoryStatsResult,
    MemorySupersedeRequest,
    MemoryContradictRequest,
    MemoryWrite,
    MemoryWriteResult,
)


def test_memory_scope_and_source_normalize_extended_fields() -> None:
    scope = MemoryScope(
        user_id=" user-1 ",
        tenant_id=" tenant-1 ",
        session_id=" session-1 ",
        agent_name=" planner ",
        source_id=" doc-a ",
        document_id=" record-1 ",
        tags=[" architecture ", "phase-2"],
        metadata={"kind": "test"},
    )
    source = MemorySource(
        source_id=" doc-a ",
        document_id=" record-1 ",
        chunk_id=" chunk-1 ",
        section_path=[" Intro ", " Memory "],
        metadata={"origin": "fixture"},
    )

    assert scope.has_explicit_scope() is True
    assert scope.has_durable_scope() is True
    assert scope.summary() == {
        "scope_type": "user",
        "user_id_present": True,
        "project_id_present": False,
        "tenant_id_present": True,
        "session_id_present": True,
        "agent_name_present": True,
        "usecase_present": False,
        "source_id_present": True,
        "document_id_present": True,
        "tag_count": 2,
    }
    assert source.section_path == ("Intro", "Memory")
    assert source.metadata == {"origin": "fixture"}


def test_memory_search_request_and_result_models_normalize_new_surface() -> None:
    record = MemoryRecord(
        memory_id="mem-1",
        text="Document chunk text",
        memory_type="document_chunk",
        scope=MemoryScope(project_id="proj-1", source_id="doc-a"),
        source=MemorySource(source_id="doc-a", chunk_id="chunk-1"),
        tags=["reference"],
    )
    hit = MemoryResult.from_record(
        record,
        score=0.82,
        score_details=MemoryScore(
            final_score=0.82,
            component_scores={"vector": 0.7},
            normalized_scores={"vector": 0.7},
        ),
        highlights=["chunk text"],
    )
    request = MemorySearchRequest(
        text=" memory adapter ",
        scope=MemoryScope(project_id="proj-1"),
        limit=6,
        filters={
            "kinds": ["document_chunk"],
            "tags": ["reference"],
            "source_ids": ["doc-a"],
        },
    )
    result = MemorySearchResult(
        results=[hit],
        query_id=" query-1 ",
        search_strategy=" hybrid ",
    )

    assert request.query == "memory adapter"
    assert request.top_k == 6
    assert request.filters is not None
    assert request.filters.kinds == ("document_chunk",)
    assert result.query_id == "query-1"
    assert result.search_strategy == "hybrid"
    assert list(result) == [hit]
    assert result[0].record.memory_id == "mem-1"
    assert result == [hit]
    assert hit.score_details is not None
    assert hit.score_details.final_score == 0.82


def test_memory_lifecycle_ingest_and_privacy_models_are_provider_neutral() -> None:
    write = MemoryWrite(
        text="Remember the architecture preference.",
        scope=MemoryScope(user_id="user-1", project_id="proj-1"),
        memory_type="user_preference",
        stable_key="pref-1",
        tags=["preference"],
        source={"source_id": "session-1", "title": "Chat session"},
    )
    lifecycle = MemoryLifecycleRequest(memory_id="mem-1", reason="confirmed")
    supersede = MemorySupersedeRequest(
        old_memory_id="mem-old",
        new_memory_id="mem-new",
        reason="updated fact",
    )
    contradict = MemoryContradictRequest(
        memory_id_a="mem-a",
        memory_id_b="mem-b",
        reason="conflicting observations",
    )
    forget = MemoryForgetRequest(memory_id="mem-1", hard_delete=True)
    ingest = DocumentIngestRequest(
        source_id="backend-memory-store-adapter-architecture.md",
        document_id="doc-memory-arch",
        scope=MemoryScope(project_id="proj-1", source_id="backend-memory-store-adapter-architecture.md"),
        content="# Memory\n\nArchitecture",
        source_hash="hash-1",
    )
    delete_request = MemoryDeleteByScopeRequest(
        scope=MemoryScope(project_id="proj-1", document_id="doc-memory-arch"),
        hard_delete=False,
    )
    export_request = MemoryExportByScopeRequest(
        scope=MemoryScope(project_id="proj-1"),
        include_content=True,
    )
    record = MemoryRecord(
        memory_id="mem-1",
        text=write.text,
        memory_type=write.memory_type,
        scope=write.scope,
        source=write.source,
        tags=write.tags,
    )
    write_result = MemoryWriteResult(
        operation="upsert",
        status="ok",
        record=record,
        affected_ids=["mem-1"],
    )
    export_result = MemoryExportResult(
        scope=export_request.scope,
        records=[record],
        exported_at="2026-06-27T00:00:00Z",
    )

    assert write.kind == "user_preference"
    assert write.source is not None
    assert write.source.source_id == "session-1"
    assert lifecycle.reason == "confirmed"
    assert supersede.old_memory_id == "mem-old"
    assert contradict.memory_id_b == "mem-b"
    assert forget.hard_delete is True
    assert ingest.source_hash == "hash-1"
    assert delete_request.scope.document_id == "doc-memory-arch"
    assert export_request.include_content is True
    assert write_result.memory_id == "mem-1"
    assert export_result.record_count == 1


def test_memory_health_stats_and_errors_are_safe_and_typed() -> None:
    health = MemoryHealthResult(
        status="ok",
        enabled=True,
        provider="memory_store",
        configured=True,
        required=False,
        schema_initialized=True,
        embedding_model_configured=True,
        embedding_dimension=384,
        search_available=True,
        ingest_available=False,
    )
    stats = MemoryStatsResult(
        total_records=3,
        scope_counts={"project": 3},
        status_counts={"active": 2, "expired": 1},
        type_counts={"document_chunk": 2, "user_preference": 1},
        provider="memory_store",
    )

    assert health["status"] == "ok"
    assert health["embedding_dimension"] == 384
    assert stats["total_records"] == 3
    assert stats.as_dict()["type_counts"] == {
        "document_chunk": 2,
        "user_preference": 1,
    }
    assert issubclass(MemoryDisabledError, MemoryGatewayError)
    assert issubclass(MemoryInvalidScopeError, MemoryGatewayError)
    assert issubclass(MemoryNotFoundError, MemoryGatewayError)
    assert issubclass(MemoryPolicyDeniedError, MemoryGatewayError)
    assert issubclass(MemoryAdapterError, MemoryGatewayError)
    assert issubclass(MemoryIngestionError, MemoryGatewayError)
    assert issubclass(MemoryPrivacyError, MemoryGatewayError)