"""Gateway-level helpers owned by the backend memory runtime package."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, NoReturn, TypeVar

from app.config.view import MemorySettings
from app.contracts.context import OrchestrationContext
from app.contracts.errors import (
    MemoryAdapterError,
    MemoryDisabledError,
    MemoryGatewayError,
    MemoryIngestionError,
    MemoryInvalidScopeError,
    MemoryPolicyApprovalRequiredError,
    MemoryPolicyDeniedError,
    MemoryPrivacyError,
    PolicyApprovalRequiredError,
    PolicyDeniedError,
)
from app.contracts.health import HEALTH_NOT_CONFIGURED, HealthStatus
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
    MemoryLifecycleRequest,
    MemoryRecord,
    MemoryScope,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryStatsResult,
    MemorySupersedeRequest,
    MemoryContradictRequest,
    MemoryWrite,
    MemoryWriteResult,
)
from app.contracts.policy import PolicyAction
from app.contracts.trace import (
    DOCUMENT_INGEST_COMPLETED,
    DOCUMENT_INGEST_FAILED,
    DOCUMENT_INGEST_STARTED,
    MEMORY_DELETE_BY_SCOPE_COMPLETED,
    MEMORY_DELETE_BY_SCOPE_FAILED,
    MEMORY_DELETE_BY_SCOPE_STARTED,
    MEMORY_EXPORT_BY_SCOPE_COMPLETED,
    MEMORY_EXPORT_BY_SCOPE_FAILED,
    MEMORY_GET_COMPLETED,
    MEMORY_GET_FAILED,
    MEMORY_GET_STARTED,
    MEMORY_LIFECYCLE_UPDATED,
    MEMORY_SEARCH_COMPLETED,
    MEMORY_SEARCH_FAILED,
    MEMORY_SEARCH_STARTED,
    MEMORY_STATS_CHECKED,
    MEMORY_WRITE_COMPLETED,
    MEMORY_WRITE_FAILED,
    MEMORY_WRITE_STARTED,
    TraceEvent,
)
from app.memory.adapters.base import MemoryAdapter
from app.memory.health import build_unavailable_memory_health
from app.memory.redaction import bound_record, bound_result, hash_text, summarize_scores
from app.memory.scopes import resolve_memory_scope, scope_summary
from app.memory.stats import build_empty_memory_stats
from app.policy.memory_policy import build_memory_policy_request

ResultT = TypeVar("ResultT")


class DefaultMemoryGateway:
    """Backend-owned memory gateway that applies scope, policy, traces, and bounds."""

    def __init__(
        self,
        *,
        settings: MemorySettings,
        adapter: MemoryAdapter,
        component: str = "app.memory.gateway",
    ) -> None:
        self._settings = settings
        self._adapter = adapter
        self._component = component

    async def close(self) -> None:
        await self._adapter.close()

    async def search(
        self,
        request: MemorySearchRequest,
        context: OrchestrationContext,
    ) -> MemorySearchResult:
        scope = self._resolve_read_scope(request.scope, context)
        limit = self._bound_search_limit(request.limit)
        max_chars = self._max_result_chars(request.max_result_chars)
        normalized_request = MemorySearchRequest(
            text=request.text,
            scope=scope,
            memory_types=request.memory_types,
            limit=limit,
            include_document_chunks=request.include_document_chunks,
            metadata=dict(request.metadata),
            filters=request.filters,
            candidate_k=request.candidate_k,
            include_agent_memories=request.include_agent_memories,
            include_graph_context=request.include_graph_context,
            max_result_chars=max_chars,
            query_id=request.query_id,
            top_k=limit,
        )
        operation_payload = {
            **scope_summary(scope),
            "operation": "search",
            "query_chars": len(normalized_request.text),
            "query_hash": hash_text(normalized_request.text),
            "top_k": limit,
            "include_document_chunks": normalized_request.include_document_chunks,
        }

        return await self._execute(
            action="memory.search",
            resource=None,
            context=context,
            scope=scope,
            disabled_result=lambda: MemorySearchResult(
                results=[],
                query_id=normalized_request.query_id,
                total_candidates=0,
                search_strategy="disabled",
            ),
            started_event=MEMORY_SEARCH_STARTED,
            completed_event=MEMORY_SEARCH_COMPLETED,
            failed_event=MEMORY_SEARCH_FAILED,
            started_payload=operation_payload,
            call=lambda: self._adapter.search(normalized_request),
            on_success=lambda raw_result, _duration_ms: self._bound_search_result(
                raw_result,
                limit=limit,
                max_chars=max_chars,
            ),
            success_payload=lambda result, duration_ms: {
                **scope_summary(scope),
                "operation": "search",
                "query_chars": len(normalized_request.text),
                "query_hash": hash_text(normalized_request.text),
                "result_count": len(result.results),
                "duration_ms": duration_ms,
                **summarize_scores(result.results),
            },
        )

    async def get(
        self,
        request: MemoryGetRequest,
        context: OrchestrationContext,
    ) -> MemoryRecord | None:
        scope = self._resolve_read_scope(request.scope, context)
        normalized_request = MemoryGetRequest(
            identifier=request.identifier,
            scope=scope,
            lookup_kind=request.lookup_kind,
            include_related=request.include_related,
            metadata=dict(request.metadata),
        )
        operation_payload = {
            **scope_summary(scope),
            "operation": "get",
            "lookup_kind": normalized_request.lookup_kind,
            "identifier_present": True,
        }

        return await self._execute(
            action="memory.get",
            resource=normalized_request.identifier,
            context=context,
            scope=scope,
            disabled_result=lambda: None,
            started_event=MEMORY_GET_STARTED,
            completed_event=MEMORY_GET_COMPLETED,
            failed_event=MEMORY_GET_FAILED,
            started_payload=operation_payload,
            call=lambda: self._adapter.get(normalized_request),
            on_success=lambda record, _duration_ms: (
                None
                if record is None
                else bound_record(record, max_chars=self._settings.defaults.max_result_chars)
            ),
            success_payload=lambda record, duration_ms: {
                **scope_summary(scope),
                "operation": "get",
                "lookup_kind": normalized_request.lookup_kind,
                "found": record is not None,
                "duration_ms": duration_ms,
                "content_chars": 0 if record is None else len(record.text),
            },
        )

    async def get_chunk_context(
        self,
        request: MemoryChunkContextRequest,
        context: OrchestrationContext,
    ) -> MemoryChunkContextResult | None:
        scope = self._resolve_read_scope(request.scope, context)
        normalized_request = MemoryChunkContextRequest(
            chunk_id=request.chunk_id,
            scope=scope,
            before=request.before,
            after=request.after,
            metadata=dict(request.metadata),
        )
        operation_payload = {
            **scope_summary(scope),
            "operation": "get_chunk_context",
            "lookup_kind": "chunk_context",
            "identifier_present": True,
            "before": normalized_request.before,
            "after": normalized_request.after,
        }

        return await self._execute(
            action="memory.get",
            resource=normalized_request.chunk_id,
            context=context,
            scope=scope,
            disabled_result=lambda: None,
            started_event=MEMORY_GET_STARTED,
            completed_event=MEMORY_GET_COMPLETED,
            failed_event=MEMORY_GET_FAILED,
            started_payload=operation_payload,
            call=lambda: self._adapter.get_chunk_context(normalized_request),
            on_success=lambda result, _duration_ms: self._bound_chunk_context_result(result),
            success_payload=lambda result, duration_ms: {
                **scope_summary(scope),
                "operation": "get_chunk_context",
                "lookup_kind": "chunk_context",
                "found": result is not None,
                "duration_ms": duration_ms,
                "result_count": 0 if result is None else len(result.ordered_results),
                "content_chars": 0
                if result is None
                else sum(len(item.text) for item in result.ordered_results),
            },
        )

    async def upsert(
        self,
        memory: MemoryWrite,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        scope = self._resolve_scope(memory.scope, context)
        self._ensure_write_scope(scope)
        normalized_memory = MemoryWrite(
            text=memory.text,
            scope=scope,
            memory_type=memory.memory_type,
            stable_key=memory.stable_key,
            importance=memory.importance,
            confidence=memory.confidence,
            ttl_days=memory.ttl_days,
            tags=memory.tags,
            source=memory.source,
            allow_retrieval=memory.allow_retrieval,
            allow_llm_context=memory.allow_llm_context,
            metadata=dict(memory.metadata),
        )
        operation_payload = {
            **scope_summary(scope),
            "operation": "upsert",
            "memory_type": normalized_memory.memory_type,
            "stable_key_present": normalized_memory.stable_key is not None,
            "content_chars": len(normalized_memory.text),
        }

        return await self._execute(
            action="memory.upsert",
            resource=normalized_memory.stable_key,
            context=context,
            scope=scope,
            require_enabled=True,
            started_event=MEMORY_WRITE_STARTED,
            completed_event=MEMORY_WRITE_COMPLETED,
            failed_event=MEMORY_WRITE_FAILED,
            started_payload=operation_payload,
            call=lambda: self._adapter.upsert(normalized_memory),
            on_success=lambda result, _duration_ms: self._bound_write_result(result),
            success_payload=lambda result, duration_ms: {
                **scope_summary(scope),
                "operation": "upsert",
                "status": result.status,
                "duration_ms": duration_ms,
                "affected_count": len(result.affected_ids),
                "memory_id_present": result.memory_id is not None,
            },
            policy_memory_write=normalized_memory,
        )

    async def promote(
        self,
        request: MemoryLifecycleRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        scope = self._resolve_scope(request.scope, context)
        self._ensure_write_scope(scope)
        normalized_request = MemoryLifecycleRequest(
            memory_id=request.memory_id,
            scope=scope,
            reason=request.reason,
            metadata=dict(request.metadata),
        )
        return await self._run_lifecycle_operation(
            action="memory.promote",
            operation="promote",
            request=normalized_request,
            context=context,
            call=lambda: self._adapter.promote(normalized_request),
        )

    async def supersede(
        self,
        request: MemorySupersedeRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        scope = self._resolve_scope(request.scope, context)
        self._ensure_write_scope(scope)
        normalized_request = MemorySupersedeRequest(
            old_memory_id=request.old_memory_id,
            new_memory_id=request.new_memory_id,
            scope=scope,
            reason=request.reason,
            metadata=dict(request.metadata),
        )
        operation_payload = {
            **scope_summary(scope),
            "operation": "supersede",
            "affected_count": 2,
        }

        return await self._execute(
            action="memory.supersede",
            resource=normalized_request.new_memory_id,
            context=context,
            scope=scope,
            require_enabled=True,
            started_event=MEMORY_WRITE_STARTED,
            completed_event=MEMORY_LIFECYCLE_UPDATED,
            failed_event=MEMORY_WRITE_FAILED,
            started_payload=operation_payload,
            call=lambda: self._adapter.supersede(normalized_request),
            on_success=lambda result, _duration_ms: self._bound_write_result(result),
            success_payload=lambda result, duration_ms: {
                **scope_summary(scope),
                "operation": "supersede",
                "status": result.status,
                "duration_ms": duration_ms,
                "affected_count": len(result.affected_ids),
            },
        )

    async def contradict(
        self,
        request: MemoryContradictRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        scope = self._resolve_scope(request.scope, context)
        self._ensure_write_scope(scope)
        normalized_request = MemoryContradictRequest(
            memory_id_a=request.memory_id_a,
            memory_id_b=request.memory_id_b,
            scope=scope,
            reason=request.reason,
            metadata=dict(request.metadata),
        )
        operation_payload = {
            **scope_summary(scope),
            "operation": "contradict",
            "affected_count": 2,
        }

        return await self._execute(
            action="memory.contradict",
            resource=normalized_request.memory_id_a,
            context=context,
            scope=scope,
            require_enabled=True,
            started_event=MEMORY_WRITE_STARTED,
            completed_event=MEMORY_LIFECYCLE_UPDATED,
            failed_event=MEMORY_WRITE_FAILED,
            started_payload=operation_payload,
            call=lambda: self._adapter.contradict(normalized_request),
            on_success=lambda result, _duration_ms: self._bound_write_result(result),
            success_payload=lambda result, duration_ms: {
                **scope_summary(scope),
                "operation": "contradict",
                "status": result.status,
                "duration_ms": duration_ms,
                "affected_count": len(result.affected_ids),
            },
        )

    async def expire(
        self,
        request: MemoryLifecycleRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        scope = self._resolve_scope(request.scope, context)
        self._ensure_write_scope(scope)
        normalized_request = MemoryLifecycleRequest(
            memory_id=request.memory_id,
            scope=scope,
            reason=request.reason,
            metadata=dict(request.metadata),
        )
        return await self._run_lifecycle_operation(
            action="memory.expire",
            operation="expire",
            request=normalized_request,
            context=context,
            call=lambda: self._adapter.expire(normalized_request),
        )

    async def forget(
        self,
        request: MemoryForgetRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        self._ensure_memory_enabled()
        if request.hard_delete:
            self._ensure_hard_delete_allowed()
        scope = self._resolve_scope(request.scope, context)
        self._ensure_write_scope(scope)
        normalized_request = MemoryForgetRequest(
            memory_id=request.memory_id,
            scope=scope,
            reason=request.reason,
            hard_delete=request.hard_delete,
            metadata=dict(request.metadata),
        )
        operation_payload = {
            **scope_summary(scope),
            "operation": "forget",
            "hard_delete": normalized_request.hard_delete,
            "affected_count": 1,
        }

        return await self._execute(
            action="memory.forget",
            resource=normalized_request.memory_id,
            context=context,
            scope=scope,
            require_enabled=True,
            started_event=MEMORY_WRITE_STARTED,
            completed_event=MEMORY_LIFECYCLE_UPDATED,
            failed_event=MEMORY_WRITE_FAILED,
            started_payload=operation_payload,
            call=lambda: self._adapter.forget(normalized_request),
            on_success=lambda result, _duration_ms: self._bound_write_result(result),
            success_payload=lambda result, duration_ms: {
                **scope_summary(scope),
                "operation": "forget",
                "status": result.status,
                "duration_ms": duration_ms,
                "affected_count": len(result.affected_ids),
                "hard_delete": normalized_request.hard_delete,
            },
        )

    async def ingest_document(
        self,
        request: DocumentIngestRequest,
        context: OrchestrationContext,
    ) -> DocumentIngestResult:
        scope = self._resolve_scope(request.scope, context)
        self._ensure_write_scope(scope)
        normalized_request = DocumentIngestRequest(
            source_id=request.source_id,
            scope=scope,
            document_id=request.document_id,
            content=request.content,
            path=request.path,
            source_uri=request.source_uri,
            source_hash=request.source_hash,
            title=request.title,
            content_type=request.content_type,
            replace_existing=request.replace_existing,
            mark_missing_chunks_removed=request.mark_missing_chunks_removed,
            metadata=dict(request.metadata),
        )
        operation_payload = {
            **scope_summary(scope),
            "operation": "ingest_document",
            "source_id_present": True,
            "document_id_present": normalized_request.document_id is not None,
            "content_chars": len(normalized_request.content or ""),
            "path_present": normalized_request.path is not None,
        }

        return await self._execute(
            action="memory.ingest_document",
            resource=normalized_request.source_id,
            context=context,
            scope=scope,
            require_enabled=True,
            started_event=DOCUMENT_INGEST_STARTED,
            completed_event=DOCUMENT_INGEST_COMPLETED,
            failed_event=DOCUMENT_INGEST_FAILED,
            started_payload=operation_payload,
            call=lambda: self._adapter.ingest_document(normalized_request),
            success_payload=lambda result, duration_ms: {
                **scope_summary(scope),
                "operation": "ingest_document",
                "duration_ms": duration_ms,
                "chunks_created": result.chunks_created,
                "chunks_updated": result.chunks_updated,
                "chunks_unchanged": result.chunks_unchanged,
                "chunks_removed": result.chunks_removed,
            },
        )

    async def delete_by_scope(
        self,
        request: MemoryDeleteByScopeRequest,
        context: OrchestrationContext,
    ) -> MemoryDeleteResult:
        self._ensure_memory_enabled()
        self._ensure_delete_by_scope_enabled()
        if request.hard_delete:
            self._ensure_hard_delete_allowed()
        self._ensure_delete_confirmation(request)
        self._ensure_explicit_durable_scope(request.scope)
        scope = self._resolve_read_scope(request.scope, context)
        self._ensure_delete_export_scope(scope)
        normalized_request = MemoryDeleteByScopeRequest(
            scope=scope,
            hard_delete=request.hard_delete,
            require_confirmation=request.require_confirmation,
            metadata=dict(request.metadata),
        )
        operation_payload = {
            **scope_summary(scope),
            "operation": "delete_by_scope",
            "hard_delete": normalized_request.hard_delete,
            "require_confirmation": normalized_request.require_confirmation,
        }

        return await self._execute(
            action="memory.delete_by_scope",
            resource=None,
            context=context,
            scope=scope,
            require_enabled=True,
            started_event=MEMORY_DELETE_BY_SCOPE_STARTED,
            completed_event=MEMORY_DELETE_BY_SCOPE_COMPLETED,
            failed_event=MEMORY_DELETE_BY_SCOPE_FAILED,
            started_payload=operation_payload,
            call=lambda: self._adapter.delete_by_scope(normalized_request),
            success_payload=lambda result, duration_ms: {
                **scope_summary(scope),
                "operation": "delete_by_scope",
                "duration_ms": duration_ms,
                "deleted_count": result.deleted_count,
                "hard_delete": result.hard_delete,
            },
        )

    async def export_by_scope(
        self,
        request: MemoryExportByScopeRequest,
        context: OrchestrationContext,
    ) -> MemoryExportResult:
        self._ensure_memory_enabled()
        self._ensure_export_by_scope_enabled()
        self._ensure_explicit_durable_scope(request.scope)
        scope = self._resolve_read_scope(request.scope, context)
        self._ensure_delete_export_scope(scope)
        normalized_request = MemoryExportByScopeRequest(
            scope=scope,
            include_content=request.include_content,
            metadata=dict(request.metadata),
        )

        return await self._execute(
            action="memory.export_by_scope",
            resource=None,
            context=context,
            scope=scope,
            require_enabled=True,
            completed_event=MEMORY_EXPORT_BY_SCOPE_COMPLETED,
            failed_event=MEMORY_EXPORT_BY_SCOPE_FAILED,
            call=lambda: self._adapter.export_by_scope(normalized_request),
            on_success=lambda result, _duration_ms: self._bound_export_result(result),
            success_payload=lambda result, duration_ms: {
                **scope_summary(scope),
                "operation": "export_by_scope",
                "duration_ms": duration_ms,
                "record_count": result.record_count,
                "include_content": normalized_request.include_content,
            },
        )

    async def health(self) -> Any:
        return await self._adapter.health()

    async def stats(
        self,
        scopes: MemoryScope | None = None,
        context: OrchestrationContext | None = None,
    ) -> MemoryStatsResult:
        if not self._settings.enabled:
            return build_empty_memory_stats(
                provider=self._settings.provider,
                configured=True,
                status="ok",
                metadata={"enabled": False},
            )
        if context is None:
            return await self._adapter.stats(scopes)

        requested_scope = MemoryScope() if scopes is None else scopes
        scope = self._resolve_read_scope(requested_scope, context)
        return await self._execute(
            action="memory.stats",
            resource=None,
            context=context,
            scope=scope,
            require_enabled=True,
            completed_event=MEMORY_STATS_CHECKED,
            call=lambda: self._adapter.stats(scope),
            success_payload=lambda result, duration_ms: {
                **scope_summary(scope),
                "operation": "stats",
                "duration_ms": duration_ms,
                "total_records": result.total_records,
                "scope_count": len(result.scope_counts),
                "status_count": len(result.status_counts),
                "type_count": len(result.type_counts),
            },
        )

    async def _run_lifecycle_operation(
        self,
        *,
        action: PolicyAction,
        operation: str,
        request: MemoryLifecycleRequest,
        context: OrchestrationContext,
        call: Callable[[], Awaitable[MemoryWriteResult]],
    ) -> MemoryWriteResult:
        scope = request.scope
        operation_payload = {
            **scope_summary(scope),
            "operation": operation,
            "affected_count": 1,
        }
        return await self._execute(
            action=action,
            resource=request.memory_id,
            context=context,
            scope=scope,
            require_enabled=True,
            started_event=MEMORY_WRITE_STARTED,
            completed_event=MEMORY_LIFECYCLE_UPDATED,
            failed_event=MEMORY_WRITE_FAILED,
            started_payload=operation_payload,
            call=call,
            on_success=lambda result, _duration_ms: self._bound_write_result(result),
            success_payload=lambda result, duration_ms: {
                **scope_summary(scope),
                "operation": operation,
                "status": result.status,
                "duration_ms": duration_ms,
                "affected_count": len(result.affected_ids),
            },
        )

    async def _execute(
        self,
        *,
        action: PolicyAction,
        resource: str | None,
        context: OrchestrationContext,
        scope: MemoryScope,
        call: Callable[[], Awaitable[ResultT]],
        success_payload: Callable[[ResultT, float], dict[str, Any]],
        started_event: str | None = None,
        completed_event: str | None = None,
        failed_event: str | None = None,
        started_payload: Mapping[str, Any] | None = None,
        disabled_result: Callable[[], ResultT] | None = None,
        require_enabled: bool = False,
        on_success: Callable[[ResultT, float], ResultT] | None = None,
        policy_memory_write: MemoryWrite | None = None,
    ) -> ResultT:
        if not self._settings.enabled:
            if disabled_result is not None:
                result = disabled_result()
                if completed_event is not None:
                    await self._record_event(
                        context,
                        event_type=completed_event,
                        payload={
                            **scope_summary(scope),
                            "operation": action.split(".", 1)[1],
                            "disabled": True,
                            **self._disabled_summary(result),
                        },
                    )
                return result
            if require_enabled:
                raise MemoryDisabledError("Memory is disabled by configuration.")

        await self._require_policy(
            action=action,
            resource=resource,
            scope=scope,
            context=context,
            memory_write=policy_memory_write,
        )

        started_at = perf_counter()
        if started_event is not None:
            await self._record_event(
                context,
                event_type=started_event,
                status="started",
                payload=dict(started_payload or {}),
            )

        try:
            raw_result = await call()
        except Exception as exc:
            duration_ms = self._duration_ms(started_at)
            if failed_event is not None:
                await self._record_event(
                    context,
                    event_type=failed_event,
                    status="failed",
                    severity="warning",
                    duration_ms=duration_ms,
                    error_type=type(exc).__name__,
                    payload={
                        **scope_summary(scope),
                        "operation": action.split(".", 1)[1],
                        "duration_ms": duration_ms,
                    },
                )
            raise self._wrap_operation_error(action=action, exc=exc) from exc

        duration_ms = self._duration_ms(started_at)
        result = raw_result if on_success is None else on_success(raw_result, duration_ms)
        if completed_event is not None:
            await self._record_event(
                context,
                event_type=completed_event,
                duration_ms=duration_ms,
                payload=success_payload(result, duration_ms),
            )
        return result

    async def _require_policy(
        self,
        *,
        action: PolicyAction,
        resource: str | None,
        scope: MemoryScope,
        context: OrchestrationContext,
        memory_write: MemoryWrite | None,
    ) -> None:
        request = build_memory_policy_request(
            action=action,
            component=self._component,
            scope=scope,
            context=context,
            resource=resource,
            provider=self._settings.provider,
            memory_write=memory_write,
        )
        try:
            await context.policy.require_allowed(request, context)
        except PolicyApprovalRequiredError as exc:
            raise MemoryPolicyApprovalRequiredError(str(exc)) from exc
        except PolicyDeniedError as exc:
            raise MemoryPolicyDeniedError(str(exc)) from exc

    def _resolve_scope(
        self,
        scope: MemoryScope,
        context: OrchestrationContext,
    ) -> MemoryScope:
        return resolve_memory_scope(
            scope,
            context=context,
            default_scope=self._settings.defaults.default_scope,
        )

    def _resolve_read_scope(
        self,
        scope: MemoryScope,
        context: OrchestrationContext,
    ) -> MemoryScope:
        explicit_scope = scope.normalized()
        resolved_scope = self._resolve_scope(scope, context)
        return MemoryScope(
            user_id=resolved_scope.user_id,
            project_id=resolved_scope.project_id,
            tenant_id=explicit_scope.tenant_id,
            session_id=explicit_scope.session_id,
            agent_name=explicit_scope.agent_name,
            usecase=explicit_scope.usecase,
            source_id=explicit_scope.source_id,
            document_id=explicit_scope.document_id,
            tags=explicit_scope.tags,
            metadata=dict(explicit_scope.metadata),
        )

    def _ensure_write_scope(self, scope: MemoryScope) -> None:
        if scope.has_durable_scope():
            return
        if self._settings.lifecycle.allow_session_scope_only_writes and scope.session_id is not None:
            return
        if self._settings.lifecycle.require_durable_scope_for_writes:
            raise MemoryInvalidScopeError(
                "Memory writes require at least one durable scope."
            )

    def _ensure_delete_export_scope(self, scope: MemoryScope) -> None:
        if not self._settings.lifecycle.require_durable_scope_for_delete_export:
            return
        if scope.has_durable_scope():
            return
        raise MemoryInvalidScopeError(
            "Delete and export operations require a durable memory scope."
        )

    def _ensure_memory_enabled(self) -> None:
        if self._settings.enabled:
            return
        raise MemoryDisabledError("Memory is disabled by configuration.")

    def _ensure_delete_by_scope_enabled(self) -> None:
        if self._settings.privacy.enable_delete_by_scope:
            return
        raise MemoryPrivacyError("Delete by scope is disabled by configuration.")

    def _ensure_export_by_scope_enabled(self) -> None:
        if self._settings.privacy.enable_export_by_scope:
            return
        raise MemoryPrivacyError("Export by scope is disabled by configuration.")

    def _ensure_hard_delete_allowed(self) -> None:
        if self._settings.privacy.hard_delete_enabled:
            return
        raise MemoryPrivacyError("Hard delete is disabled by configuration.")

    def _ensure_delete_confirmation(self, request: MemoryDeleteByScopeRequest) -> None:
        if request.require_confirmation or not self._settings.privacy.delete_by_scope_requires_confirm:
            return
        raise MemoryPrivacyError("Delete by scope requires explicit confirmation.")

    def _ensure_explicit_durable_scope(self, scope: MemoryScope) -> None:
        if scope.normalized().has_durable_scope():
            return
        raise MemoryInvalidScopeError(
            "Delete and export operations require an explicit durable scope."
        )

    def _bound_search_limit(self, value: int | None) -> int:
        limit = self._settings.defaults.top_k if value is None or value <= 0 else value
        return max(1, min(limit, self._settings.search.limit_max))

    def _max_result_chars(self, value: int | None) -> int:
        limit = self._settings.defaults.max_result_chars
        if value is None or value <= 0:
            return limit
        return min(value, limit)

    def _bound_search_result(
        self,
        result: MemorySearchResult,
        *,
        limit: int,
        max_chars: int,
    ) -> MemorySearchResult:
        bounded_results = [
            bound_result(item, max_chars=max_chars) for item in list(result.results)[:limit]
        ]
        return MemorySearchResult(
            results=bounded_results,
            query_id=result.query_id,
            total_candidates=result.total_candidates,
            search_strategy=result.search_strategy,
            metadata=dict(result.metadata),
        )

    def _bound_write_result(self, result: MemoryWriteResult) -> MemoryWriteResult:
        record = result.record
        if record is None:
            return result
        return MemoryWriteResult(
            operation=result.operation,
            status=result.status,
            record=bound_record(record, max_chars=self._settings.defaults.max_result_chars),
            changed=result.changed,
            affected_ids=result.affected_ids,
            metadata=dict(result.metadata),
        )

    def _bound_chunk_context_result(
        self,
        result: MemoryChunkContextResult | None,
    ) -> MemoryChunkContextResult | None:
        if result is None:
            return None

        max_chars = self._settings.defaults.max_result_chars
        return MemoryChunkContextResult(
            chunk=bound_result(result.chunk, max_chars=max_chars),
            before=[bound_result(item, max_chars=max_chars) for item in result.before],
            after=[bound_result(item, max_chars=max_chars) for item in result.after],
            metadata=dict(result.metadata),
        )

    def _bound_export_result(self, result: MemoryExportResult) -> MemoryExportResult:
        return MemoryExportResult(
            scope=result.scope,
            records=[
                bound_record(record, max_chars=self._settings.defaults.max_result_chars)
                for record in result.records
            ],
            exported_at=result.exported_at,
            metadata=dict(result.metadata),
        )

    async def _record_event(
        self,
        context: OrchestrationContext,
        *,
        event_type: str,
        payload: Mapping[str, Any],
        status: str = "completed",
        severity: str = "info",
        duration_ms: float | None = None,
        error_type: str | None = None,
    ) -> None:
        try:
            await context.trace.record_event(
                TraceEvent(
                    trace_id=context.request.trace_id or "trace_memory",
                    session_id=context.request.session_id,
                    event_type=event_type,
                    component=self._component,
                    timestamp=datetime.now(UTC),
                    status=status,
                    severity=severity,
                    user_id=context.request.user_id,
                    usecase=context.request.usecase,
                    agent_name=self._optional_text(context.runtime_metadata.get("agent_name")),
                    strategy_name=self._optional_text(
                        context.runtime_metadata.get("strategy_name")
                    ),
                    provider=self._settings.provider,
                    duration_ms=duration_ms,
                    error_type=error_type,
                    payload=dict(payload),
                )
            )
        except Exception:
            return None

    def _disabled_summary(self, result: object) -> dict[str, Any]:
        if isinstance(result, MemorySearchResult):
            return {"result_count": len(result.results)}
        if result is None:
            return {"found": False}
        return {}

    def _wrap_operation_error(
        self,
        *,
        action: PolicyAction,
        exc: Exception,
    ) -> MemoryGatewayError:
        if isinstance(exc, MemoryGatewayError):
            return exc
        if action == "memory.ingest_document":
            return MemoryIngestionError("Memory document ingestion failed.")
        if action in {"memory.delete_by_scope", "memory.export_by_scope"}:
            return MemoryPrivacyError("Memory privacy operation failed.")
        return MemoryAdapterError("Memory adapter operation failed.")

    @staticmethod
    def _duration_ms(started_at: float) -> float:
        return max((perf_counter() - started_at) * 1000.0, 0.0)

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None


class UnavailableMemoryGateway:
    """Public memory gateway used when the configured provider is unavailable."""

    def __init__(
        self,
        *,
        provider: str,
        required: bool,
        reason: str,
        status: HealthStatus = HEALTH_NOT_CONFIGURED,
    ) -> None:
        self._provider = provider
        self._required = required
        self._reason = reason
        self._status = status

    async def close(self) -> None:
        return None

    async def search(
        self,
        request: MemorySearchRequest,
        context: object,
    ) -> MemorySearchResult:
        self._raise_unavailable("search")

    async def get(
        self,
        request: MemoryGetRequest,
        context: object,
    ) -> MemoryRecord | None:
        self._raise_unavailable("get")

    async def get_chunk_context(
        self,
        request: MemoryChunkContextRequest,
        context: object,
    ) -> MemoryChunkContextResult | None:
        self._raise_unavailable("get_chunk_context")

    async def upsert(
        self,
        memory: MemoryWrite,
        context: object,
    ) -> MemoryWriteResult:
        self._raise_unavailable("upsert")

    async def promote(
        self,
        request: MemoryLifecycleRequest,
        context: object,
    ) -> MemoryWriteResult:
        self._raise_unavailable("promote")

    async def supersede(
        self,
        request: MemorySupersedeRequest,
        context: object,
    ) -> MemoryWriteResult:
        self._raise_unavailable("supersede")

    async def contradict(
        self,
        request: MemoryContradictRequest,
        context: object,
    ) -> MemoryWriteResult:
        self._raise_unavailable("contradict")

    async def expire(
        self,
        request: MemoryLifecycleRequest,
        context: object,
    ) -> MemoryWriteResult:
        self._raise_unavailable("expire")

    async def forget(
        self,
        request: MemoryForgetRequest,
        context: object,
    ) -> MemoryWriteResult:
        self._raise_unavailable("forget")

    async def ingest_document(
        self,
        request: DocumentIngestRequest,
        context: object,
    ) -> DocumentIngestResult:
        self._raise_unavailable("ingest_document")

    async def delete_by_scope(
        self,
        request: MemoryDeleteByScopeRequest,
        context: object,
    ) -> MemoryDeleteResult:
        self._raise_unavailable("delete_by_scope")

    async def export_by_scope(
        self,
        request: MemoryExportByScopeRequest,
        context: object,
    ) -> MemoryExportResult:
        self._raise_unavailable("export_by_scope")

    async def health(self) -> Mapping[str, Any]:
        return dict(
            build_unavailable_memory_health(
                provider=self._provider,
                required=self._required,
                reason=self._reason,
                status=self._status,
            )
        )

    async def stats(
        self,
        scopes: MemoryScope | None = None,
        context: object | None = None,
    ) -> MemoryStatsResult:
        return build_empty_memory_stats(
            provider=self._provider,
            configured=False,
            status=self._status,
            metadata={"reason": self._reason},
        )

    def _raise_unavailable(self, operation: str) -> NoReturn:
        message = f"Memory gateway is not available for {operation}."
        if self._provider in {"", "disabled", "none"} or self._reason == "disabled":
            raise MemoryDisabledError(message)
        raise MemoryGatewayError(message)