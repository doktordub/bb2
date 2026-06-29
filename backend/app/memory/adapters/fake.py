"""Deterministic internal fake adapter for memory-package unit tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.contracts.memory import (
    DocumentIngestRequest,
    DocumentIngestResult,
    MemoryChunkContextRequest,
    MemoryChunkContextResult,
    MemoryDeleteByScopeRequest,
    MemoryDeleteResult,
    MemoryExportByScopeRequest,
    MemoryExportResult,
    MemoryForgetRequest,
    MemoryGetRequest,
    MemoryHealthResult,
    MemoryLifecycleRequest,
    MemoryRecord,
    MemoryScope,
    MemoryResult,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryStatsResult,
    MemorySupersedeRequest,
    MemoryContradictRequest,
    MemorySource,
    MemoryWrite,
    MemoryWriteResult,
)
from app.memory.health import coerce_memory_health_result
from app.memory.stats import build_empty_memory_stats, filter_records_by_scope, summarize_records


class FakeMemoryAdapter:
    """Deterministic adapter that mirrors the public memory shapes without context."""

    def __init__(
        self,
        results: list[MemoryResult] | MemorySearchResult | None = None,
        *,
        search_error: Exception | None = None,
        get_error: Exception | None = None,
        upsert_error: Exception | None = None,
        lifecycle_error: Exception | None = None,
        ingest_error: Exception | None = None,
        privacy_error: Exception | None = None,
        forget_error: Exception | None = None,
        health_payload: MemoryHealthResult | dict[str, Any] | None = None,
        health_error: Exception | None = None,
        stats_payload: MemoryStatsResult | dict[str, Any] | None = None,
        stats_error: Exception | None = None,
    ) -> None:
        if isinstance(results, MemorySearchResult):
            self.search_result = MemorySearchResult(
                results=list(results.results),
                query_id=results.query_id,
                total_candidates=results.total_candidates,
                search_strategy=results.search_strategy,
                metadata=dict(results.metadata),
            )
        else:
            self.search_result = MemorySearchResult(results=list(results or []))

        self.records: dict[str, MemoryRecord] = {}
        self.search_requests: list[MemorySearchRequest] = []
        self.get_requests: list[MemoryGetRequest] = []
        self.chunk_context_requests: list[MemoryChunkContextRequest] = []
        self.writes: list[MemoryWrite] = []
        self.lifecycle_requests: list[MemoryLifecycleRequest] = []
        self.supersede_requests: list[MemorySupersedeRequest] = []
        self.contradict_requests: list[MemoryContradictRequest] = []
        self.forget_requests: list[MemoryForgetRequest] = []
        self.ingest_requests: list[DocumentIngestRequest] = []
        self.delete_requests: list[MemoryDeleteByScopeRequest] = []
        self.export_requests: list[MemoryExportByScopeRequest] = []
        self.initialize_calls = 0
        self.close_calls = 0
        self._search_error = search_error
        self._get_error = get_error
        self._upsert_error = upsert_error
        self._lifecycle_error = lifecycle_error
        self._ingest_error = ingest_error
        self._privacy_error = privacy_error
        self._forget_error = forget_error
        self._health_payload = coerce_memory_health_result(
            health_payload
            or {
                "status": "ok",
                "enabled": True,
                "provider": "fake",
                "configured": True,
                "search_available": True,
                "ingest_available": True,
            },
            provider="fake",
            required=False,
        )
        self._health_error = health_error
        self._stats_payload = (
            stats_payload
            if isinstance(stats_payload, MemoryStatsResult)
            else build_empty_memory_stats(provider="fake", configured=True, status="ok")
            if stats_payload is None
            else MemoryStatsResult(**dict(stats_payload))
        )
        self._stats_error = stats_error

    async def initialize(self) -> None:
        self.initialize_calls += 1

    async def close(self) -> None:
        self.close_calls += 1

    async def search(self, request: MemorySearchRequest) -> MemorySearchResult:
        if self._search_error is not None:
            raise self._search_error
        self.search_requests.append(request)
        return MemorySearchResult(
            results=list(self.search_result.results),
            query_id=request.query_id,
            total_candidates=self.search_result.total_candidates,
            search_strategy=self.search_result.search_strategy,
            metadata=dict(self.search_result.metadata),
        )

    async def get(self, request: MemoryGetRequest) -> MemoryRecord | None:
        if self._get_error is not None:
            raise self._get_error
        self.get_requests.append(request)
        if request.lookup_kind == "chunk":
            for record in self.records.values():
                if record.chunk_id == request.identifier:
                    return record
            return None
        return self.records.get(request.identifier)

    async def get_chunk_context(
        self,
        request: MemoryChunkContextRequest,
    ) -> MemoryChunkContextResult | None:
        if self._get_error is not None:
            raise self._get_error
        self.chunk_context_requests.append(request)

        target_record: MemoryRecord | None = None
        for record in self.records.values():
            if record.chunk_id == request.chunk_id:
                target_record = record
                break
        if target_record is None:
            return None

        source_id = target_record.source_id
        related = [
            record
            for record in self.records.values()
            if record.memory_type == "document_chunk"
            and record.source_id == source_id
            and _source_chunk_index(record) is not None
        ]
        related.sort(key=lambda record: (_source_chunk_index(record) or 0, record.memory_id))
        target_index = next(
            (
                index
                for index, record in enumerate(related)
                if record.memory_id == target_record.memory_id
            ),
            None,
        )
        if target_index is None:
            return MemoryChunkContextResult(chunk=MemoryResult.from_record(target_record))

        before_records = related[max(0, target_index - request.before) : target_index]
        after_records = related[target_index + 1 : target_index + 1 + request.after]
        return MemoryChunkContextResult(
            chunk=MemoryResult.from_record(target_record),
            before=[MemoryResult.from_record(record) for record in before_records],
            after=[MemoryResult.from_record(record) for record in after_records],
        )

    async def upsert(self, memory: MemoryWrite) -> MemoryWriteResult:
        if self._upsert_error is not None:
            raise self._upsert_error
        self.writes.append(memory)
        memory_id = memory.stable_key or f"fake_memory_{len(self.writes)}"
        record = MemoryRecord(
            memory_id=memory_id,
            text=memory.text,
            memory_type=memory.memory_type,
            scope=memory.scope,
            metadata=dict(memory.metadata),
            source=memory.source,
            importance=memory.importance,
            confidence=memory.confidence,
            tags=memory.tags,
        )
        self.records[memory_id] = record
        return MemoryWriteResult(
            operation="upsert",
            status="ok",
            record=record,
            affected_ids=(memory_id,),
        )

    async def promote(self, request: MemoryLifecycleRequest) -> MemoryWriteResult:
        return await self._run_lifecycle_operation("promote", request)

    async def supersede(self, request: MemorySupersedeRequest) -> MemoryWriteResult:
        if self._lifecycle_error is not None:
            raise self._lifecycle_error
        self.supersede_requests.append(request)
        old_record = self.records.get(request.old_memory_id)
        if old_record is not None:
            old_record.status = "superseded"
        return MemoryWriteResult(
            operation="supersede",
            status="ok",
            record=self.records.get(request.new_memory_id),
            affected_ids=(request.old_memory_id, request.new_memory_id),
        )

    async def contradict(self, request: MemoryContradictRequest) -> MemoryWriteResult:
        if self._lifecycle_error is not None:
            raise self._lifecycle_error
        self.contradict_requests.append(request)
        for memory_id in (request.memory_id_a, request.memory_id_b):
            record = self.records.get(memory_id)
            if record is not None:
                record.status = "contradicted"
        return MemoryWriteResult(
            operation="contradict",
            status="ok",
            affected_ids=(request.memory_id_a, request.memory_id_b),
        )

    async def expire(self, request: MemoryLifecycleRequest) -> MemoryWriteResult:
        return await self._run_lifecycle_operation("expire", request)

    async def forget(self, request: MemoryForgetRequest) -> MemoryWriteResult:
        if self._forget_error is not None:
            raise self._forget_error
        self.forget_requests.append(request)
        record = self.records.pop(request.memory_id, None)
        return MemoryWriteResult(
            operation="forget",
            status="forgotten",
            record=record,
            changed=record is not None,
            affected_ids=(request.memory_id,),
        )

    async def ingest_document(self, request: DocumentIngestRequest) -> DocumentIngestResult:
        if self._ingest_error is not None:
            raise self._ingest_error
        self.ingest_requests.append(request)
        created = 1 if request.content is not None or request.path is not None else 0
        return DocumentIngestResult(
            source_id=request.source_id,
            document_id=request.document_id,
            source_hash=request.source_hash,
            status="completed",
            chunks_created=created,
            chunks_updated=0,
            chunks_unchanged=0,
            chunks_removed=0,
            skipped_unchanged_document=False,
        )

    async def delete_by_scope(
        self,
        request: MemoryDeleteByScopeRequest,
    ) -> MemoryDeleteResult:
        if self._privacy_error is not None:
            raise self._privacy_error
        self.delete_requests.append(request)
        matching = filter_records_by_scope(self.records.values(), request.scope)
        for record in matching:
            self.records.pop(record.memory_id, None)
        return MemoryDeleteResult(
            scope=request.scope,
            deleted_count=len(matching),
            hard_delete=request.hard_delete,
        )

    async def export_by_scope(
        self,
        request: MemoryExportByScopeRequest,
    ) -> MemoryExportResult:
        if self._privacy_error is not None:
            raise self._privacy_error
        self.export_requests.append(request)
        matching = filter_records_by_scope(self.records.values(), request.scope)
        return MemoryExportResult(
            scope=request.scope,
            records=matching,
            exported_at="fake-export",
        )

    async def health(self) -> MemoryHealthResult:
        if self._health_error is not None:
            raise self._health_error
        return self._health_payload

    async def stats(self, scopes: MemoryScope | None = None) -> MemoryStatsResult:
        if self._stats_error is not None:
            raise self._stats_error
        if scopes is None and isinstance(self._stats_payload, MemoryStatsResult):
            if self._stats_payload.total_records == 0 and self.records:
                return summarize_records(self.records.values(), provider="fake")
            return self._stats_payload

        relevant_records = filter_records_by_scope(self.records.values(), scopes)
        return summarize_records(relevant_records, provider="fake")

    async def _run_lifecycle_operation(
        self,
        operation: str,
        request: MemoryLifecycleRequest,
    ) -> MemoryWriteResult:
        if self._lifecycle_error is not None:
            raise self._lifecycle_error
        self.lifecycle_requests.append(request)
        record = self.records.get(request.memory_id)
        if record is not None:
            record.status = operation
        return MemoryWriteResult(
            operation=operation,
            status="ok",
            record=record,
            changed=record is not None,
            affected_ids=(request.memory_id,),
        )


def _source_chunk_index(record: MemoryRecord) -> int | None:
    source = record.source
    if isinstance(source, MemorySource):
        return source.chunk_index
    if isinstance(source, Mapping):
        value = source.get("chunk_index")
        return value if isinstance(value, int) else None
    return None