"""In-memory fake memory gateway for contract-focused tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.contracts.context import OrchestrationContext
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


class FakeMemoryGateway:
    """Deterministic memory fake that records reads and writes."""

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
        self.results = self.search_result.results
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
        self.forgotten_ids: list[str] = []
        self.contexts: list[OrchestrationContext] = []
        self._search_error = search_error
        self._get_error = get_error
        self._upsert_error = upsert_error
        self._lifecycle_error = lifecycle_error
        self._ingest_error = ingest_error
        self._privacy_error = privacy_error
        self._forget_error = forget_error
        self._health_payload = _coerce_health_payload(health_payload)
        self._health_error = health_error
        self._stats_payload = _coerce_stats_payload(stats_payload)
        self._stats_error = stats_error

    async def search(
        self,
        request: MemorySearchRequest,
        context: OrchestrationContext,
    ) -> MemorySearchResult:
        if self._search_error is not None:
            raise self._search_error
        self.search_requests.append(request)
        self.contexts.append(context)
        return MemorySearchResult(
            results=list(self.search_result.results),
            query_id=request.query_id,
            total_candidates=self.search_result.total_candidates,
            search_strategy=self.search_result.search_strategy,
            metadata=dict(self.search_result.metadata),
        )

    async def get(
        self,
        request: MemoryGetRequest,
        context: OrchestrationContext,
    ) -> MemoryRecord | None:
        if self._get_error is not None:
            raise self._get_error
        self.get_requests.append(request)
        self.contexts.append(context)
        if request.lookup_kind == "chunk":
            for record in self.records.values():
                if record.chunk_id == request.identifier:
                    return record
            return None
        return self.records.get(request.identifier)

    async def get_chunk_context(
        self,
        request: MemoryChunkContextRequest,
        context: OrchestrationContext,
    ) -> MemoryChunkContextResult | None:
        if self._get_error is not None:
            raise self._get_error
        self.chunk_context_requests.append(request)
        self.contexts.append(context)

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

    async def upsert(
        self,
        memory: MemoryWrite,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        if self._upsert_error is not None:
            raise self._upsert_error
        self.writes.append(memory)
        self.contexts.append(context)
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

    async def promote(
        self,
        request: MemoryLifecycleRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        return await self._run_lifecycle_operation("promote", request, context)

    async def supersede(
        self,
        request: MemorySupersedeRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        if self._lifecycle_error is not None:
            raise self._lifecycle_error
        self.supersede_requests.append(request)
        self.contexts.append(context)
        old_record = self.records.get(request.old_memory_id)
        if old_record is not None:
            old_record.status = "superseded"
        return MemoryWriteResult(
            operation="supersede",
            status="ok",
            record=self.records.get(request.new_memory_id),
            affected_ids=(request.old_memory_id, request.new_memory_id),
        )

    async def contradict(
        self,
        request: MemoryContradictRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        if self._lifecycle_error is not None:
            raise self._lifecycle_error
        self.contradict_requests.append(request)
        self.contexts.append(context)
        for memory_id in (request.memory_id_a, request.memory_id_b):
            record = self.records.get(memory_id)
            if record is not None:
                record.status = "contradicted"
        return MemoryWriteResult(
            operation="contradict",
            status="ok",
            affected_ids=(request.memory_id_a, request.memory_id_b),
        )

    async def expire(
        self,
        request: MemoryLifecycleRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        return await self._run_lifecycle_operation("expire", request, context)

    async def forget(
        self,
        request: MemoryForgetRequest | str,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        if self._forget_error is not None:
            raise self._forget_error
        normalized_request = (
            request
            if isinstance(request, MemoryForgetRequest)
            else MemoryForgetRequest(memory_id=request)
        )
        self.forget_requests.append(normalized_request)
        self.contexts.append(context)
        self.forgotten_ids.append(normalized_request.memory_id)
        record = self.records.pop(normalized_request.memory_id, None)
        return MemoryWriteResult(
            operation="forget",
            status="forgotten",
            record=record,
            changed=record is not None,
            affected_ids=(normalized_request.memory_id,),
        )

    async def ingest_document(
        self,
        request: DocumentIngestRequest,
        context: OrchestrationContext,
    ) -> DocumentIngestResult:
        if self._ingest_error is not None:
            raise self._ingest_error
        self.ingest_requests.append(request)
        self.contexts.append(context)
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
        context: OrchestrationContext,
    ) -> MemoryDeleteResult:
        if self._privacy_error is not None:
            raise self._privacy_error
        self.delete_requests.append(request)
        self.contexts.append(context)
        matching_ids = [
            memory_id
            for memory_id, record in self.records.items()
            if _scope_matches(record.scope, request.scope)
        ]
        for memory_id in matching_ids:
            self.records.pop(memory_id, None)
        return MemoryDeleteResult(
            scope=request.scope,
            deleted_count=len(matching_ids),
            hard_delete=request.hard_delete,
        )

    async def export_by_scope(
        self,
        request: MemoryExportByScopeRequest,
        context: OrchestrationContext,
    ) -> MemoryExportResult:
        if self._privacy_error is not None:
            raise self._privacy_error
        self.export_requests.append(request)
        self.contexts.append(context)
        return MemoryExportResult(
            scope=request.scope,
            records=[
                record
                for record in self.records.values()
                if _scope_matches(record.scope, request.scope)
            ],
            exported_at="fake-export",
        )

    async def health(self) -> MemoryHealthResult:
        if self._health_error is not None:
            raise self._health_error
        return self._health_payload

    async def stats(
        self,
        scopes: Any = None,
        context: OrchestrationContext | None = None,
    ) -> MemoryStatsResult:
        if self._stats_error is not None:
            raise self._stats_error
        if self._stats_payload is not None:
            return self._stats_payload

        relevant_records = list(self.records.values())
        if scopes is not None:
            relevant_records = [
                record for record in relevant_records if _scope_matches(record.scope, scopes)
            ]

        type_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for record in relevant_records:
            type_counts[record.memory_type] = type_counts.get(record.memory_type, 0) + 1
            status_counts[record.status] = status_counts.get(record.status, 0) + 1

        return MemoryStatsResult(
            total_records=len(relevant_records),
            scope_counts={"scoped": len(relevant_records)},
            status_counts=status_counts,
            type_counts=type_counts,
            provider="fake",
        )

    async def _run_lifecycle_operation(
        self,
        operation: str,
        request: MemoryLifecycleRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        if self._lifecycle_error is not None:
            raise self._lifecycle_error
        self.lifecycle_requests.append(request)
        self.contexts.append(context)
        record = self.records.get(request.memory_id)
        if record is not None:
            if operation == "promote":
                record.importance = 1.0
            if operation == "expire":
                record.status = "expired"
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


def _coerce_health_payload(
    payload: MemoryHealthResult | dict[str, Any] | None,
) -> MemoryHealthResult:
    if isinstance(payload, MemoryHealthResult):
        return payload
    if isinstance(payload, dict):
        return MemoryHealthResult(**payload)
    return MemoryHealthResult(
        status="ok",
        enabled=True,
        provider="fake",
        configured=True,
        search_available=True,
        ingest_available=True,
    )


def _coerce_stats_payload(
    payload: MemoryStatsResult | dict[str, Any] | None,
) -> MemoryStatsResult | None:
    if isinstance(payload, MemoryStatsResult):
        return payload
    if isinstance(payload, dict):
        return MemoryStatsResult(**payload)
    return None


def _scope_matches(candidate: Any, scope: Any) -> bool:
    candidate_user = getattr(candidate, "user_id", None)
    candidate_project = getattr(candidate, "project_id", None)
    candidate_tenant = getattr(candidate, "tenant_id", None)
    candidate_session = getattr(candidate, "session_id", None)
    candidate_agent = getattr(candidate, "agent_name", None)
    candidate_usecase = getattr(candidate, "usecase", None)
    candidate_source = getattr(candidate, "source_id", None)
    candidate_document = getattr(candidate, "document_id", None)
    scope_user = getattr(scope, "user_id", None)
    scope_project = getattr(scope, "project_id", None)
    scope_tenant = getattr(scope, "tenant_id", None)
    scope_session = getattr(scope, "session_id", None)
    scope_agent = getattr(scope, "agent_name", None)
    scope_usecase = getattr(scope, "usecase", None)
    scope_source = getattr(scope, "source_id", None)
    scope_document = getattr(scope, "document_id", None)
    scope_tags = tuple(getattr(scope, "tags", ()))
    candidate_tags = tuple(getattr(candidate, "tags", ()))

    return all(
        (
            scope_user is None or candidate_user == scope_user,
            scope_project is None or candidate_project == scope_project,
            scope_tenant is None or candidate_tenant == scope_tenant,
            scope_session is None or candidate_session == scope_session,
            scope_agent is None or candidate_agent == scope_agent,
            scope_usecase is None or candidate_usecase == scope_usecase,
            scope_source is None or candidate_source == scope_source,
            scope_document is None or candidate_document == scope_document,
            not scope_tags or all(tag in candidate_tags for tag in scope_tags),
        )
    )