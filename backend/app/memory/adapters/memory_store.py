"""Backend-owned adapter for the external memory_store package."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from app.contracts.health import HEALTH_DEGRADED, HEALTH_FAILED, HEALTH_OK
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
    MemoryResult,
    MemoryScore,
    MemoryScope,
    MemorySearchFilters,
    MemorySearchRequest,
    MemorySearchResult,
    MemorySource,
    MemoryStatsResult,
    MemorySupersedeRequest,
    MemoryContradictRequest,
    MemoryWrite,
    MemoryWriteResult,
)
from app.memory.errors import (
    MemoryAdapterError,
    MemoryDisabledError,
    MemoryIngestionError,
    MemoryPrivacyError,
)
from app.memory.stats import summarize_records
from app.persistence.settings import MemoryStoreSettings


_NON_DOCUMENT_MEMORY_TYPES = (
    "user_preference",
    "project_fact",
    "task_state",
    "conversation_summary",
    "decision",
    "observation",
    "error_debug_note",
)

_BACKEND_SCOPE_METADATA_KEY = "_backend_scope"
_BACKEND_SOURCE_METADATA_KEY = "_backend_source"


@dataclass(frozen=True, slots=True)
class _MemoryStoreRuntime:
    MemoryCreate: type[Any]
    MemorySearchQuery: type[Any]
    MemoryService: type[Any]
    Scope: type[Any]


def _load_memory_store_runtime() -> _MemoryStoreRuntime:
    service_module = import_module("memory_store.service")
    models_module = import_module("memory_store.models")
    return _MemoryStoreRuntime(
        MemoryCreate=getattr(models_module, "MemoryCreate"),
        MemorySearchQuery=getattr(models_module, "MemorySearchQuery"),
        MemoryService=getattr(service_module, "MemoryService"),
        Scope=getattr(models_module, "Scope"),
    )


def _resolve_runtime_loader() -> Any:
    try:
        from app.persistence import memory_store_adapter as compatibility_module
    except Exception:
        return _load_memory_store_runtime

    loader = getattr(compatibility_module, "_load_memory_store_runtime", None)
    if callable(loader):
        return loader
    return _load_memory_store_runtime


class MemoryStoreAdapter:
    """Async backend adapter around the sync memory_store service."""

    def __init__(self, settings: MemoryStoreSettings, *, required: bool) -> None:
        self._settings = settings
        self._required = required
        self._runtime: _MemoryStoreRuntime | None = None
        self._service: Any | None = None
        self._initialization_error: Exception | None = None
        self._initialization_lock = asyncio.Lock()
        self._fastembed_env_previous: tuple[str | None, str | None] | None = None

    async def initialize(self) -> None:
        await self._ensure_service()

    async def close(self) -> None:
        service = self._service
        self._service = None
        if service is not None:
            close = getattr(service, "close", None)
            if callable(close):
                await asyncio.to_thread(close)
        self._restore_fastembed_environment()

    async def search(self, request: MemorySearchRequest) -> MemorySearchResult:
        if not isinstance(request.text, str) or request.text.strip() == "":
            raise MemoryAdapterError("Memory search requires non-empty text.")

        limit = normalize_memory_search_limit(
            request.limit,
            default_limit=self._settings.search_limit_default,
            max_limit=self._settings.search_limit_max,
        )
        query_memory_types = _resolve_query_memory_types(request)
        if query_memory_types == []:
            return MemorySearchResult(
                results=[],
                query_id=request.query_id,
                total_candidates=0,
                search_strategy="memory_store",
            )

        query_statuses = _resolve_query_statuses(request.filters)
        include_removed = _status_enabled(request.filters, "removed")
        include_forgotten = _status_enabled(request.filters, "forgotten")

        try:
            runtime = self._get_runtime()
            query = runtime.MemorySearchQuery(
                text=request.text,
                scope=self._to_store_scope(runtime, request.scope),
                limit=limit,
                memory_types=query_memory_types,
                statuses=query_statuses,
                include_removed=include_removed,
                include_forgotten=include_forgotten,
                allow_retrieval_only=True,
            )
            service = await self._ensure_service()
            raw_results = await asyncio.to_thread(service.search, query)
        except Exception as exc:
            raise MemoryAdapterError("Memory search failed.") from exc

        raw_results = _filter_raw_search_results(raw_results, request)
        results = [self._map_search_result(item, fallback_scope=request.scope) for item in raw_results]
        return MemorySearchResult(
            results=results,
            query_id=request.query_id,
            total_candidates=len(results),
            search_strategy="memory_store",
        )

    async def get(self, request: MemoryGetRequest) -> MemoryRecord | None:
        try:
            service = await self._ensure_service()
            runtime = self._get_runtime()
            if request.lookup_kind == "chunk":
                raw_record = await asyncio.to_thread(
                    service.get_chunk,
                    request.identifier,
                    scope=self._to_store_scope(runtime, request.scope),
                )
                return self._map_chunk_record(raw_record, fallback_scope=request.scope)

            raw_record = await asyncio.to_thread(service.get_memory, request.identifier)
        except Exception as exc:
            raise MemoryAdapterError("Memory lookup failed.") from exc

        if raw_record is None:
            return None
        return self._map_record(raw_record, fallback_scope=request.scope)

    async def get_chunk_context(
        self,
        request: MemoryChunkContextRequest,
    ) -> MemoryChunkContextResult | None:
        try:
            service = await self._ensure_service()
            runtime = self._get_runtime()
            raw_context = await asyncio.to_thread(
                service.get_chunk_context,
                request.chunk_id,
                scope=self._to_store_scope(runtime, request.scope),
                before=request.before,
                after=request.after,
            )
        except Exception as exc:
            if exc.__class__.__name__ == "MemoryNotFoundError":
                return None
            raise MemoryAdapterError("Memory chunk-context lookup failed.") from exc

        return MemoryChunkContextResult(
            chunk=self._map_chunk_result(getattr(raw_context, "chunk"), fallback_scope=request.scope),
            before=[
                self._map_chunk_result(item, fallback_scope=request.scope)
                for item in getattr(raw_context, "before", ())
            ],
            after=[
                self._map_chunk_result(item, fallback_scope=request.scope)
                for item in getattr(raw_context, "after", ())
            ],
        )

    async def upsert(self, memory: MemoryWrite) -> MemoryWriteResult:
        if not self._settings.allow_writes:
            raise MemoryDisabledError("Memory writes are disabled by configuration.")

        try:
            runtime = self._get_runtime()
            source = _coerce_source(memory)
            create = runtime.MemoryCreate(
                text=memory.text,
                scope=self._to_store_scope(runtime, memory.scope),
                stable_key=memory.stable_key,
                memory_type=memory.memory_type,
                importance=memory.importance if memory.importance is not None else 0.5,
                confidence=memory.confidence if memory.confidence is not None else 0.5,
                tags=list(memory.tags),
                title=_source_title(memory),
                source_hash=_source_hash(memory),
                source_uri=_source_uri(memory),
                chunk_id=_source_chunk_id(memory),
                heading_path=list(_source_heading_path(memory)),
                document_chunk_index=_source_chunk_index(memory),
                allow_retrieval=True if memory.allow_retrieval is None else memory.allow_retrieval,
                allow_llm_context=True if memory.allow_llm_context is None else memory.allow_llm_context,
                metadata=_build_write_metadata(memory, source=source),
            )
            service = await self._ensure_service()
            raw_record = await asyncio.to_thread(
                service.upsert_memory,
                create,
                memory.stable_key,
                embed=False,
            )
        except Exception as exc:
            raise MemoryAdapterError("Memory upsert failed.") from exc

        record = self._map_record(raw_record, fallback_scope=memory.scope)
        return MemoryWriteResult(
            operation="upsert",
            status="ok",
            record=record,
            affected_ids=(record.memory_id,),
        )

    async def promote(self, request: MemoryLifecycleRequest) -> MemoryWriteResult:
        return await self._run_single_record_lifecycle(
            operation="promote",
            memory_id=request.memory_id,
            scope=request.scope,
            reason=request.reason,
            runner=lambda service: service.promote(request.memory_id, reason=request.reason),
        )

    async def supersede(self, request: MemorySupersedeRequest) -> MemoryWriteResult:
        try:
            service = await self._ensure_service()
            await asyncio.to_thread(
                service.supersede,
                request.old_memory_id,
                request.new_memory_id,
                reason=request.reason,
            )
            raw_record = await asyncio.to_thread(service.get_memory, request.new_memory_id)
        except Exception as exc:
            raise MemoryAdapterError("Memory supersede failed.") from exc

        record = None if raw_record is None else self._map_record(raw_record, fallback_scope=request.scope)
        return MemoryWriteResult(
            operation="supersede",
            status="ok",
            record=record,
            affected_ids=(request.old_memory_id, request.new_memory_id),
        )

    async def contradict(self, request: MemoryContradictRequest) -> MemoryWriteResult:
        try:
            service = await self._ensure_service()
            await asyncio.to_thread(
                service.contradict,
                request.memory_id_a,
                request.memory_id_b,
                reason=request.reason,
            )
        except Exception as exc:
            raise MemoryAdapterError("Memory contradict failed.") from exc

        return MemoryWriteResult(
            operation="contradict",
            status="ok",
            affected_ids=(request.memory_id_a, request.memory_id_b),
        )

    async def expire(self, request: MemoryLifecycleRequest) -> MemoryWriteResult:
        return await self._run_single_record_lifecycle(
            operation="expire",
            memory_id=request.memory_id,
            scope=request.scope,
            reason=request.reason,
            runner=lambda service: service.expire(request.memory_id, reason=request.reason),
        )

    async def forget(self, request: MemoryForgetRequest) -> MemoryWriteResult:
        if not self._settings.allow_writes:
            raise MemoryDisabledError("Memory writes are disabled by configuration.")

        existing = await self.get(MemoryGetRequest(identifier=request.memory_id, scope=request.scope))
        try:
            service = await self._ensure_service()
            await asyncio.to_thread(service.forget, request.memory_id)
        except Exception as exc:
            raise MemoryAdapterError("Memory forget failed.") from exc

        return MemoryWriteResult(
            operation="forget",
            status="forgotten",
            record=existing,
            changed=existing is not None,
            affected_ids=(request.memory_id,),
        )

    async def ingest_document(self, request: DocumentIngestRequest) -> DocumentIngestResult:
        cleanup_path = False
        if request.path is not None:
            ingest_path = Path(request.path)
        elif request.content is not None:
            ingest_path = self._prepare_inline_ingest_path(request)
            ingest_path.parent.mkdir(parents=True, exist_ok=True)
            ingest_path.write_text(request.content, encoding="utf-8")
            cleanup_path = True
        else:
            raise MemoryIngestionError("Document ingestion requires a path or inline content.")

        try:
            service = await self._ensure_service()
            runtime = self._get_runtime()
            raw_result = await asyncio.to_thread(
                service.ingest_document,
                ingest_path,
                self._to_store_scope(runtime, request.scope),
            )
        except Exception as exc:
            raise MemoryIngestionError("Memory document ingestion failed.") from exc
        finally:
            if cleanup_path:
                ingest_path.unlink(missing_ok=True)

        return DocumentIngestResult(
            source_id=request.source_id,
            document_id=request.document_id,
            source_hash=request.source_hash,
            status="completed",
            chunks_created=_read_int(raw_result, "added"),
            chunks_updated=_read_int(raw_result, "updated"),
            chunks_unchanged=_read_int(raw_result, "unchanged"),
            chunks_removed=_read_int(raw_result, "removed"),
            skipped_unchanged_document=(
                _read_int(raw_result, "added") == 0
                and _read_int(raw_result, "updated") == 0
                and _read_int(raw_result, "unchanged") > 0
            ),
            metadata={"path": str(getattr(raw_result, "path", ingest_path))},
        )

    async def delete_by_scope(
        self,
        request: MemoryDeleteByScopeRequest,
    ) -> MemoryDeleteResult:
        if not self._settings.allow_writes:
            raise MemoryDisabledError("Memory writes are disabled by configuration.")

        try:
            service = await self._ensure_service()
            runtime = self._get_runtime()
            if _requires_backend_scope_filtering(request.scope):
                if request.hard_delete:
                    raise MemoryPrivacyError(
                        "Hard delete by extended backend scope is not supported safely."
                    )

                exported = await asyncio.to_thread(
                    service.export_scope,
                    self._to_store_scope(runtime, request.scope),
                )
                matching_records = [
                    record
                    for record in getattr(exported, "records", ())
                    if _raw_record_matches_scope(record, request.scope)
                ]
                for record in matching_records:
                    await asyncio.to_thread(service.forget, str(getattr(record, "memory_id")))
                return MemoryDeleteResult(
                    scope=request.scope,
                    deleted_count=len(matching_records),
                    hard_delete=False,
                )

            deleted_count = await asyncio.to_thread(
                service.delete_by_scope,
                self._to_store_scope(runtime, request.scope),
                hard_delete=request.hard_delete,
            )
        except Exception as exc:
            raise MemoryAdapterError("Memory delete-by-scope failed.") from exc

        return MemoryDeleteResult(
            scope=request.scope,
            deleted_count=int(deleted_count),
            hard_delete=request.hard_delete,
        )

    async def export_by_scope(
        self,
        request: MemoryExportByScopeRequest,
    ) -> MemoryExportResult:
        try:
            service = await self._ensure_service()
            runtime = self._get_runtime()
            exported = await asyncio.to_thread(
                service.export_scope,
                self._to_store_scope(runtime, request.scope),
            )
        except Exception as exc:
            raise MemoryAdapterError("Memory export-by-scope failed.") from exc

        records = [
            self._map_record(record, fallback_scope=request.scope)
            for record in getattr(exported, "records", ())
            if _raw_record_matches_scope(record, request.scope)
        ]
        if not request.include_content:
            records = [replace(record, text="[redacted]") for record in records]
        exported_at = _stringify_datetime(getattr(exported, "exported_at", None))
        return MemoryExportResult(
            scope=request.scope,
            records=records,
            exported_at=exported_at,
        )

    async def health(self) -> dict[str, Any]:
        base = {
            "configured": True,
            "enabled": True,
            "provider": "memory_store",
            "required": self._required,
            "config_path_configured": self._settings.config_path is not None,
            "database_path_configured": self._settings.database_path is not None,
            "service_initialized": self._service is not None,
            "embedding_model_configured": bool(self._settings.embedding_model),
            "embedding_dimension": self._settings.embedding_dimension,
            "search_available": False,
            "ingest_available": False,
        }

        config_issue = self._configuration_issue()
        if config_issue is not None:
            reason, error_type = config_issue
            return {
                **base,
                "status": self._problem_status(),
                "reason": reason,
                "error": reason,
                "error_type": error_type,
            }

        try:
            runtime = self._get_runtime()
        except Exception as exc:
            return {
                **base,
                "status": self._problem_status(),
                "reason": "dependency_unavailable",
                "error": "dependency_unavailable",
                "error_type": type(exc).__name__,
            }

        payload: dict[str, Any] = {
            **base,
            "status": HEALTH_OK,
            "dependency_available": runtime is not None,
            "search_available": True,
            "ingest_available": True,
        }

        if self._service is not None:
            try:
                raw_health = await asyncio.to_thread(self._service.health)
            except Exception as exc:
                return {
                    **base,
                    "status": self._problem_status(),
                    "reason": "health_check_failed",
                    "error": "health_check_failed",
                    "error_type": type(exc).__name__,
                }

            dependencies = getattr(raw_health, "dependencies", None)
            if isinstance(dependencies, Mapping):
                payload["dependencies"] = {
                    str(name): bool(value) for name, value in dependencies.items()
                }

            schema_version = getattr(raw_health, "schema_version", None)
            if isinstance(schema_version, int):
                payload["schema_initialized"] = True
                payload["schema_version"] = schema_version

        if self._initialization_error is not None:
            return {
                **base,
                "status": self._problem_status(),
                "reason": "initialization_failed",
                "error": "initialization_failed",
                "error_type": type(self._initialization_error).__name__,
            }

        return payload

    async def stats(self, scopes: MemoryScope | None = None) -> MemoryStatsResult:
        try:
            service = await self._ensure_service()
            if scopes is None:
                raw_stats = await asyncio.to_thread(service.stats)
                return MemoryStatsResult(
                    total_records=_read_int(raw_stats, "total_records"),
                    scope_counts=_read_int_mapping(getattr(raw_stats, "scope_counts", None)),
                    status_counts=_read_int_mapping(getattr(raw_stats, "status_counts", None)),
                    type_counts=_read_int_mapping(getattr(raw_stats, "type_counts", None)),
                    status="ok",
                    provider="memory_store",
                    configured=True,
                )

            exported = await self.export_by_scope(
                MemoryExportByScopeRequest(scope=scopes, include_content=True)
            )
            return summarize_records(exported.records, provider="memory_store")
        except Exception as exc:
            raise MemoryAdapterError("Memory stats failed.") from exc

    def _get_runtime(self) -> _MemoryStoreRuntime:
        if self._runtime is None:
            loader = _resolve_runtime_loader()
            self._runtime = loader()
        return self._runtime

    async def _ensure_service(self) -> Any:
        if self._service is not None:
            return self._service
        if self._initialization_error is not None:
            raise self._initialization_error

        async with self._initialization_lock:
            if self._service is not None:
                return self._service
            if self._initialization_error is not None:
                raise self._initialization_error

            try:
                service = await asyncio.to_thread(self._build_service)
            except Exception as exc:
                self._initialization_error = exc
                raise

            self._service = service
            return service

    def _build_service(self) -> Any:
        self._apply_fastembed_environment()
        try:
            runtime = self._get_runtime()
            overrides: dict[str, Any] = {
                "database": {
                    "schema_version": self._settings.schema_version,
                },
                "embeddings": {
                    "provider": self._settings.embedding_provider,
                    "model": self._settings.embedding_model,
                    "model_version": self._settings.embedding_model_version,
                    "dim": self._settings.embedding_dimension,
                    "batch_size": self._settings.embedding_batch_size,
                    "normalize": self._settings.embedding_normalize,
                    "dimension_mismatch": self._settings.embedding_dimension_mismatch,
                },
                "reranker": {
                    "enabled": self._settings.reranker_enabled,
                    "provider": self._settings.reranker_provider,
                    "model": self._settings.reranker_model,
                    "model_version": self._settings.reranker_model_version,
                    "top_n": self._settings.reranker_top_n,
                },
                "retrieval": {
                    "vector_top_n": self._settings.retrieval_vector_top_n,
                    "fts_top_n": self._settings.retrieval_fts_top_n,
                    "rrf_k": self._settings.retrieval_rrf_k,
                    "graph_expansion_enabled": self._settings.retrieval_graph_expansion_enabled,
                    "graph_expansion_hops": self._settings.retrieval_graph_expansion_hops,
                    "final_top_k": self._settings.retrieval_final_top_k,
                    "include_component_scores": self._settings.retrieval_include_component_scores,
                    "include_debug": self._settings.retrieval_include_debug,
                },
                "scoring": {
                    "weights": {
                        "reranker": self._settings.scoring_weight_reranker,
                        "retrieval_fusion": self._settings.scoring_weight_retrieval_fusion,
                        "vector": self._settings.scoring_weight_vector,
                        "full_text": self._settings.scoring_weight_full_text,
                        "temporal": self._settings.scoring_weight_temporal,
                        "importance": self._settings.scoring_weight_importance,
                        "confidence": self._settings.scoring_weight_confidence,
                        "graph": self._settings.scoring_weight_graph,
                        "user_rating": self._settings.scoring_weight_user_rating,
                    }
                },
                "chunking": {
                    "strategy": self._settings.chunking_strategy,
                    "max_tokens": self._settings.chunking_max_tokens,
                    "overlap_tokens": self._settings.chunking_overlap_tokens,
                    "include_heading_path": self._settings.chunking_include_heading_path,
                    "include_frontmatter_in_embedding": self._settings.chunking_include_frontmatter_in_embedding,
                    "preserve_code_blocks": self._settings.chunking_preserve_code_blocks,
                    "removed_chunk_policy": self._settings.chunking_removed_chunk_policy,
                },
                "privacy": {
                    "default_sensitivity": self._settings.privacy_default_sensitivity,
                    "allow_llm_context_default": self._settings.privacy_allow_llm_context_default,
                    "allow_retrieval_default": self._settings.privacy_allow_retrieval_default,
                    "delete_by_scope_requires_confirm": self._settings.privacy_delete_by_scope_requires_confirm,
                },
            }
            if self._settings.database_path is not None:
                overrides["database"]["path"] = str(self._settings.database_path)

            if self._settings.config_path is not None:
                return runtime.MemoryService.from_config(self._settings.config_path, **overrides)
            return runtime.MemoryService.from_config(None, **overrides)
        except Exception:
            self._restore_fastembed_environment()
            raise

    def _apply_fastembed_environment(self) -> None:
        if self._fastembed_env_previous is not None:
            return

        self._fastembed_env_previous = (
            os.environ.get("FASTEMBED_CACHE_PATH"),
            os.environ.get("HF_HUB_OFFLINE"),
        )

        if self._settings.fastembed_cache_path is not None:
            os.environ["FASTEMBED_CACHE_PATH"] = str(self._settings.fastembed_cache_path)

        if self._settings.fastembed_local_files_only:
            os.environ["HF_HUB_OFFLINE"] = "1"
        else:
            os.environ.pop("HF_HUB_OFFLINE", None)

    def _restore_fastembed_environment(self) -> None:
        previous = self._fastembed_env_previous
        if previous is None:
            return

        previous_cache_path, previous_offline = previous
        if self._settings.fastembed_cache_path is not None:
            if previous_cache_path is None:
                os.environ.pop("FASTEMBED_CACHE_PATH", None)
            else:
                os.environ["FASTEMBED_CACHE_PATH"] = previous_cache_path

        if previous_offline is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = previous_offline

        self._fastembed_env_previous = None

    async def _run_single_record_lifecycle(
        self,
        *,
        operation: str,
        memory_id: str,
        scope: MemoryScope,
        reason: str | None,
        runner: Callable[[Any], Any],
    ) -> MemoryWriteResult:
        try:
            service = await self._ensure_service()
            raw_record = await asyncio.to_thread(runner, service)
        except Exception as exc:
            raise MemoryAdapterError(f"Memory {operation} failed.") from exc

        if raw_record is None:
            fetched = await self.get(MemoryGetRequest(identifier=memory_id, scope=scope))
            return MemoryWriteResult(
                operation=operation,
                status="ok",
                record=fetched,
                changed=fetched is not None,
                affected_ids=(memory_id,),
            )

        record = self._map_record(raw_record, fallback_scope=scope)
        return MemoryWriteResult(
            operation=operation,
            status="ok",
            record=record,
            affected_ids=(memory_id,),
        )

    def _to_store_scope(self, runtime: _MemoryStoreRuntime, scope: MemoryScope) -> Any:
        return runtime.Scope(
            user_id=scope.user_id,
            project_id=scope.project_id,
            agent_id=scope.agent_name,
        )

    def _from_store_scope(self, value: object, fallback_scope: MemoryScope) -> MemoryScope:
        return self._from_store_scope_with_metadata(
            value,
            fallback_scope=fallback_scope,
            metadata=None,
        )

    def _from_store_scope_with_metadata(
        self,
        value: object,
        *,
        fallback_scope: MemoryScope,
        metadata: object | None,
    ) -> MemoryScope:
        stored_scope = _read_internal_scope_metadata(metadata)
        stored_source = _read_internal_source_metadata(metadata)
        if value is None:
            return MemoryScope(
                user_id=stored_scope.user_id or fallback_scope.user_id,
                project_id=stored_scope.project_id or fallback_scope.project_id,
                tenant_id=stored_scope.tenant_id or fallback_scope.tenant_id,
                session_id=stored_scope.session_id or fallback_scope.session_id,
                agent_name=stored_scope.agent_name or fallback_scope.agent_name,
                usecase=stored_scope.usecase or fallback_scope.usecase,
                source_id=(
                    stored_scope.source_id
                    or (stored_source.source_id if stored_source is not None else None)
                    or fallback_scope.source_id
                ),
                document_id=(
                    stored_scope.document_id
                    or (stored_source.document_id if stored_source is not None else None)
                    or fallback_scope.document_id
                ),
                tags=stored_scope.tags or fallback_scope.tags,
                metadata=_merge_scope_metadata(fallback_scope.metadata, stored_scope.metadata),
            )
        user_id = (
            _optional_text(getattr(value, "user_id", None))
            or stored_scope.user_id
            or fallback_scope.user_id
        )
        project_id = (
            _optional_text(getattr(value, "project_id", None))
            or stored_scope.project_id
            or fallback_scope.project_id
        )
        agent_name = (
            _optional_text(getattr(value, "agent_id", None))
            or stored_scope.agent_name
            or fallback_scope.agent_name
        )
        return MemoryScope(
            user_id=user_id,
            project_id=project_id,
            tenant_id=stored_scope.tenant_id or fallback_scope.tenant_id,
            session_id=stored_scope.session_id or fallback_scope.session_id,
            agent_name=agent_name,
            usecase=stored_scope.usecase or fallback_scope.usecase,
            source_id=(
                stored_scope.source_id
                or (stored_source.source_id if stored_source is not None else None)
                or fallback_scope.source_id
            ),
            document_id=(
                stored_scope.document_id
                or (stored_source.document_id if stored_source is not None else None)
                or fallback_scope.document_id
            ),
            tags=stored_scope.tags or fallback_scope.tags,
            metadata=_merge_scope_metadata(fallback_scope.metadata, stored_scope.metadata),
        )

    def _map_search_result(self, result: Any, *, fallback_scope: MemoryScope) -> MemoryResult:
        record = getattr(result, "record", getattr(result, "memory", None))
        if record is None:
            raise MemoryAdapterError("Memory search returned an invalid result record.")

        mapped_record = self._map_record(record, fallback_scope=fallback_scope)
        score = getattr(result, "final_score", None)
        return MemoryResult.from_record(
            mapped_record,
            score=float(score) if isinstance(score, (int, float)) else None,
            score_details=_build_memory_score(
                result,
                include_debug=self._settings.retrieval_include_debug,
            ),
            metadata=dict(mapped_record.metadata),
        )

    def _map_chunk_result(self, result: Any, *, fallback_scope: MemoryScope) -> MemoryResult:
        mapped_record = self._map_chunk_record(result, fallback_scope=fallback_scope)
        if mapped_record is None:
            raise MemoryAdapterError("Memory chunk result was missing a record.")
        score = _read_optional_float(getattr(result, "final_score", None))
        return MemoryResult.from_record(
            mapped_record,
            score=score,
            score_details=_build_memory_score(
                result,
                include_debug=self._settings.retrieval_include_debug,
            ),
            metadata=dict(mapped_record.metadata),
        )

    def _map_record(self, record: Any, *, fallback_scope: MemoryScope) -> MemoryRecord:
        raw_metadata = getattr(record, "metadata", None)
        stored_source = _read_internal_source_metadata(raw_metadata)
        source = MemorySource(
            source_id=_first_text(
                stored_source.source_id if stored_source is not None else None,
                getattr(record, "source_hash", None),
                getattr(record, "source_path", None),
                getattr(record, "source_uri", None),
                getattr(record, "stable_key", None),
            ),
            document_id=(
                stored_source.document_id if stored_source is not None else None
            )
            or fallback_scope.document_id,
            chunk_id=_optional_text(getattr(record, "chunk_id", None)),
            source_uri=_first_text(
                getattr(record, "source_uri", None),
                getattr(record, "source_path", None),
            ),
            source_hash=_optional_text(getattr(record, "source_hash", None)),
            chunk_index=(
                stored_source.chunk_index
                if stored_source is not None and stored_source.chunk_index is not None
                else _read_optional_int(
                getattr(record, "document_chunk_index", None)
                if getattr(record, "document_chunk_index", None) is not None
                else getattr(record, "chunk_index", None)
                )
            ),
            section_path=_read_text_tuple(getattr(record, "heading_path", None)),
            title=_optional_text(getattr(record, "title", None)),
            metadata={} if stored_source is None else dict(stored_source.metadata),
        )
        return MemoryRecord(
            memory_id=str(getattr(record, "memory_id")),
            text=str(getattr(record, "text")),
            memory_type=_enum_or_text(getattr(record, "memory_type", None)) or "observation",
            scope=self._from_store_scope_with_metadata(
                getattr(record, "scope", None),
                fallback_scope=fallback_scope,
                metadata=raw_metadata,
            ),
            metadata=_public_record_metadata(raw_metadata),
            status=_enum_or_text(getattr(record, "status", None)) or "active",
            source=source,
            importance=_read_optional_float(getattr(record, "importance", None)),
            confidence=_read_optional_float(getattr(record, "confidence", None)),
            created_at=_stringify_datetime(getattr(record, "created_at", None)),
            updated_at=_stringify_datetime(getattr(record, "updated_at", None)),
            expires_at=_stringify_datetime(getattr(record, "expires_at", None)),
            tags=_read_text_tuple(getattr(record, "tags", None)),
            title=_optional_text(getattr(record, "title", None)),
            summary=_optional_text(getattr(record, "summary", None)),
        )

    def _map_chunk_record(
        self,
        record: Any,
        *,
        fallback_scope: MemoryScope,
    ) -> MemoryRecord | None:
        if record is None:
            return None
        if hasattr(record, "memory") or hasattr(record, "record"):
            mapped = self._map_search_result(record, fallback_scope=fallback_scope).record
            if isinstance(mapped, MemoryRecord):
                return mapped
            return self._map_record(record, fallback_scope=fallback_scope)

        raw_metadata = getattr(record, "metadata", None)
        stored_source = _read_internal_source_metadata(raw_metadata)
        source = MemorySource(
            source_id=_first_text(
                stored_source.source_id if stored_source is not None else None,
                getattr(record, "source_hash", None),
                getattr(record, "source_path", None),
                getattr(record, "chunk_id", None),
            ),
            document_id=(
                stored_source.document_id if stored_source is not None else None
            )
            or fallback_scope.document_id,
            chunk_id=_optional_text(getattr(record, "chunk_id", None)),
            source_uri=_first_text(
                getattr(record, "source_uri", None),
                getattr(record, "source_path", None),
            ),
            source_hash=_optional_text(getattr(record, "source_hash", None)),
            chunk_index=(
                stored_source.chunk_index
                if stored_source is not None and stored_source.chunk_index is not None
                else _first_int(
                    getattr(record, "document_chunk_index", None),
                    getattr(record, "section_chunk_index", None),
                    getattr(record, "chunk_index", None),
                )
            ),
            section_path=_read_text_tuple(getattr(record, "heading_path", None)),
            title=_optional_text(getattr(record, "title", None)),
            metadata={} if stored_source is None else dict(stored_source.metadata),
        )
        return MemoryRecord(
            memory_id=str(getattr(record, "memory_id")),
            text=str(getattr(record, "text")),
            memory_type="document_chunk",
            scope=self._from_store_scope_with_metadata(
                getattr(record, "scope", None),
                fallback_scope=fallback_scope,
                metadata=raw_metadata,
            ),
            metadata=_public_record_metadata(raw_metadata),
            status="active",
            source=source,
            created_at=_stringify_datetime(getattr(record, "created_at", None)),
            updated_at=_stringify_datetime(getattr(record, "updated_at", None)),
            tags=_read_text_tuple(getattr(record, "tags", None)),
            title=_optional_text(getattr(record, "title", None)),
            summary=_optional_text(getattr(record, "summary", None)),
        )

    def _configuration_issue(self) -> tuple[str, str] | None:
        config_path = self._settings.config_path
        if config_path is not None and not Path(config_path).exists():
            return ("config_path_missing", "FileNotFoundError")
        return None

    def _prepare_inline_ingest_path(self, request: DocumentIngestRequest) -> Path:
        if self._settings.database_path is not None:
            base_dir = self._settings.database_path.parent / ".memory_ingest"
        elif self._settings.config_path is not None:
            base_dir = self._settings.config_path.parent / ".memory_ingest"
        else:
            base_dir = Path.cwd() / ".memory_ingest"
        stable_name = request.document_id or request.source_id
        safe_stem = "".join(
            character if character.isalnum() or character in {"-", "_"} else "_"
            for character in stable_name
        ).strip("_")
        if safe_stem == "":
            safe_stem = "document"
        return base_dir / f"{safe_stem}.md"

    def _problem_status(self) -> str:
        return HEALTH_FAILED if self._required else HEALTH_DEGRADED


def normalize_memory_search_limit(
    limit: int | None,
    *,
    default_limit: int,
    max_limit: int,
) -> int:
    """Clamp search limits to backend-configured defaults and maxima."""

    if limit is None or limit <= 0:
        limit = default_limit
    return max(1, min(limit, max_limit))


def _resolve_query_memory_types(request: MemorySearchRequest) -> list[str] | None:
    request_types = _normalize_text_list(request.memory_types)
    filters = request.filters if isinstance(request.filters, MemorySearchFilters) else None
    filter_types = _normalize_text_list(filters.kinds if filters is not None else None)

    if request_types and filter_types:
        request_set = set(request_types)
        resolved = [item for item in request_types if item in request_set and item in set(filter_types)]
    elif request_types:
        resolved = request_types
    elif filter_types:
        resolved = filter_types
    elif not request.include_document_chunks:
        resolved = list(_NON_DOCUMENT_MEMORY_TYPES)
    else:
        return None

    if not request.include_document_chunks:
        resolved = [item for item in resolved if item != "document_chunk"]

    return resolved


def _resolve_query_statuses(filters: MemorySearchFilters | Mapping[str, Any] | None) -> list[str] | None:
    if not isinstance(filters, MemorySearchFilters):
        return None
    statuses = _normalize_text_list(filters.status)
    return statuses or None


def _status_enabled(
    filters: MemorySearchFilters | Mapping[str, Any] | None,
    status: str,
) -> bool:
    if not isinstance(filters, MemorySearchFilters):
        return False
    return status in filters.status


def _filter_raw_search_results(
    results: list[Any],
    request: MemorySearchRequest,
) -> list[Any]:
    return [result for result in results if _raw_search_result_matches(result, request)]


def _raw_search_result_matches(result: Any, request: MemorySearchRequest) -> bool:
    record = getattr(result, "record", getattr(result, "memory", None))
    if record is None:
        return False

    stored_scope = _stored_scope_from_raw_record(record)
    if not request.include_agent_memories and stored_scope.agent_name is not None:
        return False
    if not _stored_scope_matches(stored_scope, request.scope):
        return False

    filters = request.filters if isinstance(request.filters, MemorySearchFilters) else None
    if filters is None:
        return True
    return _raw_record_matches_filters(record, filters)


def _raw_record_matches_scope(record: Any, expected: MemoryScope) -> bool:
    return _stored_scope_matches(_stored_scope_from_raw_record(record), expected)


def _stored_scope_matches(stored: MemoryScope, expected: MemoryScope) -> bool:
    normalized_expected = expected.normalized()
    return all(
        (
            normalized_expected.user_id is None
            or normalized_expected.user_id == stored.user_id,
            normalized_expected.project_id is None
            or normalized_expected.project_id == stored.project_id,
            normalized_expected.tenant_id is None
            or normalized_expected.tenant_id == stored.tenant_id,
            normalized_expected.session_id is None
            or normalized_expected.session_id == stored.session_id,
            normalized_expected.agent_name is None
            or normalized_expected.agent_name == stored.agent_name,
            normalized_expected.usecase is None
            or normalized_expected.usecase == stored.usecase,
            normalized_expected.source_id is None
            or normalized_expected.source_id == stored.source_id,
            normalized_expected.document_id is None
            or normalized_expected.document_id == stored.document_id,
            not normalized_expected.tags
            or all(tag in stored.tags for tag in normalized_expected.tags),
        )
    )


def _raw_record_matches_filters(record: Any, filters: MemorySearchFilters) -> bool:
    memory_type = _enum_or_text(getattr(record, "memory_type", None)) or "observation"
    if filters.kinds and memory_type not in filters.kinds:
        return False

    status = _enum_or_text(getattr(record, "status", None)) or "active"
    if filters.status and status not in filters.status:
        return False

    tags = _read_text_tuple(getattr(record, "tags", None))
    if filters.tags and not all(tag in tags for tag in filters.tags):
        return False

    stored_scope = _stored_scope_from_raw_record(record)
    if filters.source_ids and stored_scope.source_id not in filters.source_ids:
        return False
    if filters.document_ids and stored_scope.document_id not in filters.document_ids:
        return False

    created_at = _read_raw_record_datetime(record)
    created_after = _parse_iso_datetime(filters.created_after)
    if created_after is not None and (created_at is None or created_at < created_after):
        return False
    created_before = _parse_iso_datetime(filters.created_before)
    if created_before is not None and (created_at is None or created_at > created_before):
        return False

    return True


def _stored_scope_from_raw_record(record: Any) -> MemoryScope:
    wrapper_scope = getattr(record, "scope", None)
    metadata = getattr(record, "metadata", None)
    stored_scope = _read_internal_scope_metadata(metadata)
    stored_source = _read_internal_source_metadata(metadata)
    return MemoryScope(
        user_id=_optional_text(getattr(wrapper_scope, "user_id", None)) or stored_scope.user_id,
        project_id=_optional_text(getattr(wrapper_scope, "project_id", None))
        or stored_scope.project_id,
        tenant_id=stored_scope.tenant_id,
        session_id=stored_scope.session_id,
        agent_name=_optional_text(getattr(wrapper_scope, "agent_id", None))
        or stored_scope.agent_name,
        usecase=stored_scope.usecase,
        source_id=stored_scope.source_id
        or (stored_source.source_id if stored_source is not None else None),
        document_id=stored_scope.document_id
        or (stored_source.document_id if stored_source is not None else None),
        tags=stored_scope.tags,
        metadata=dict(stored_scope.metadata),
    )


def _requires_backend_scope_filtering(scope: MemoryScope) -> bool:
    normalized = scope.normalized()
    return any(
        (
            normalized.tenant_id,
            normalized.session_id,
            normalized.usecase,
            normalized.source_id,
            normalized.document_id,
            normalized.tags,
        )
    )


def _build_memory_score(
    result: Any,
    *,
    include_debug: bool,
) -> MemoryScore | None:
    final_score = _read_optional_float(getattr(result, "final_score", None))
    component_scores = _coerce_float_mapping(getattr(result, "component_scores", None))
    normalized_scores = _coerce_float_mapping(getattr(result, "normalized_scores", None))
    if final_score is None and not component_scores and not normalized_scores:
        return None

    metadata = _copy_mapping(getattr(result, "debug", None)) if include_debug else {}
    return MemoryScore(
        final_score=final_score,
        vector_score=_score_component(component_scores, normalized_scores, "vector"),
        bm25_score=_score_component(component_scores, normalized_scores, "full_text", "bm25"),
        reranker_score=_score_component(component_scores, normalized_scores, "reranker"),
        temporal_score=_score_component(component_scores, normalized_scores, "temporal"),
        importance_score=_score_component(component_scores, normalized_scores, "importance"),
        user_rating_score=_score_component(component_scores, normalized_scores, "user_rating"),
        graph_score=_score_component(component_scores, normalized_scores, "graph"),
        component_scores=component_scores,
        normalized_scores=normalized_scores,
        metadata=metadata,
    )


def _score_component(
    component_scores: Mapping[str, float],
    normalized_scores: Mapping[str, float],
    *names: str,
) -> float | None:
    for name in names:
        if name in component_scores:
            return component_scores[name]
        if name in normalized_scores:
            return normalized_scores[name]
    return None


def _build_write_metadata(
    memory: MemoryWrite,
    *,
    source: MemorySource | None,
) -> dict[str, Any]:
    metadata = _copy_mapping(memory.metadata)
    scope_payload = _serialize_internal_scope(memory.scope)
    if scope_payload:
        metadata[_BACKEND_SCOPE_METADATA_KEY] = scope_payload
    source_payload = _serialize_internal_source(source)
    if source_payload:
        metadata[_BACKEND_SOURCE_METADATA_KEY] = source_payload
    return metadata


def _serialize_internal_scope(scope: MemoryScope) -> dict[str, Any]:
    normalized = scope.normalized()
    payload: dict[str, Any] = {}
    if normalized.user_id is not None:
        payload["user_id"] = normalized.user_id
    if normalized.project_id is not None:
        payload["project_id"] = normalized.project_id
    if normalized.tenant_id is not None:
        payload["tenant_id"] = normalized.tenant_id
    if normalized.session_id is not None:
        payload["session_id"] = normalized.session_id
    if normalized.agent_name is not None:
        payload["agent_name"] = normalized.agent_name
    if normalized.usecase is not None:
        payload["usecase"] = normalized.usecase
    if normalized.source_id is not None:
        payload["source_id"] = normalized.source_id
    if normalized.document_id is not None:
        payload["document_id"] = normalized.document_id
    if normalized.tags:
        payload["tags"] = list(normalized.tags)
    if normalized.metadata:
        metadata = dict(normalized.metadata)
        metadata.pop("project_scope_resolution", None)
        metadata.pop("project_scope_allowed_count", None)
        if metadata:
            payload["metadata"] = metadata
    return payload


def _serialize_internal_source(source: MemorySource | None) -> dict[str, Any]:
    if source is None:
        return {}
    payload: dict[str, Any] = {}
    if source.source_id is not None:
        payload["source_id"] = source.source_id
    if source.document_id is not None:
        payload["document_id"] = source.document_id
    if source.chunk_index is not None:
        payload["chunk_index"] = source.chunk_index
    if source.metadata:
        payload["metadata"] = dict(source.metadata)
    return payload


def _read_internal_scope_metadata(metadata: Any) -> MemoryScope:
    if not isinstance(metadata, Mapping):
        return MemoryScope()
    raw = metadata.get(_BACKEND_SCOPE_METADATA_KEY)
    if not isinstance(raw, Mapping):
        return MemoryScope()
    return MemoryScope(
        user_id=_optional_text(raw.get("user_id")),
        project_id=_optional_text(raw.get("project_id")),
        tenant_id=_optional_text(raw.get("tenant_id")),
        session_id=_optional_text(raw.get("session_id")),
        agent_name=_optional_text(raw.get("agent_name")),
        usecase=_optional_text(raw.get("usecase")),
        source_id=_optional_text(raw.get("source_id")),
        document_id=_optional_text(raw.get("document_id")),
        tags=_read_text_tuple(raw.get("tags")),
        metadata=_copy_mapping(raw.get("metadata")),
    )


def _read_internal_source_metadata(metadata: Any) -> MemorySource | None:
    if not isinstance(metadata, Mapping):
        return None
    raw = metadata.get(_BACKEND_SOURCE_METADATA_KEY)
    if not isinstance(raw, Mapping):
        return None
    return MemorySource(
        source_id=_optional_text(raw.get("source_id")),
        document_id=_optional_text(raw.get("document_id")),
        chunk_index=_read_optional_int(raw.get("chunk_index")),
        metadata=_copy_mapping(raw.get("metadata")),
    )


def _public_record_metadata(metadata: Any) -> dict[str, Any]:
    public = _copy_mapping(metadata)
    public.pop(_BACKEND_SCOPE_METADATA_KEY, None)
    public.pop(_BACKEND_SOURCE_METADATA_KEY, None)
    return public


def _merge_scope_metadata(
    fallback_metadata: Mapping[str, Any],
    stored_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(fallback_metadata)
    merged.update(stored_metadata)
    return merged


def _coerce_float_mapping(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, float] = {}
    for key, item in value.items():
        if isinstance(item, (int, float)):
            result[str(key)] = float(item)
    return result


def _normalize_text_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    result: list[str] = []
    for value in values:
        normalized = _optional_text(value)
        if normalized is not None:
            result.append(normalized)
    return result


def _first_int(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int):
            return value
    return None


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip()
    if normalized == "":
        return None
    candidate = normalized.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _read_raw_record_datetime(record: Any) -> datetime | None:
    value = getattr(record, "created_at", None)
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return _parse_iso_datetime(str(isoformat()))
    return _parse_iso_datetime(_optional_text(value))


def _copy_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _read_int_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        if isinstance(item, int):
            result[str(key)] = item
    return result


def _enum_or_text(value: Any) -> str | None:
    if value is None:
        return None
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str) and enum_value.strip() != "":
        return enum_value
    return _optional_text(value)


def _first_text(*values: Any) -> str | None:
    for value in values:
        normalized = _optional_text(value)
        if normalized is not None:
            return normalized
    return None


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _read_optional_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _read_int(value: Any, attribute: str) -> int:
    resolved = getattr(value, attribute, 0)
    return resolved if isinstance(resolved, int) else 0


def _read_optional_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _read_text_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    normalized = [_optional_text(item) for item in value]
    return tuple(item for item in normalized if item is not None)


def _stringify_datetime(value: Any) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return _optional_text(value)


def _source_title(memory: MemoryWrite) -> str | None:
    source = _coerce_source(memory)
    if source is None:
        return None
    return source.title


def _source_hash(memory: MemoryWrite) -> str | None:
    source = _coerce_source(memory)
    if source is None:
        return None
    return source.source_hash


def _source_uri(memory: MemoryWrite) -> str | None:
    source = _coerce_source(memory)
    if source is None:
        return None
    return source.source_uri


def _source_chunk_id(memory: MemoryWrite) -> str | None:
    source = _coerce_source(memory)
    if source is None:
        return None
    return source.chunk_id


def _source_heading_path(memory: MemoryWrite) -> tuple[str, ...]:
    source = _coerce_source(memory)
    if source is None:
        return ()
    return source.section_path


def _source_chunk_index(memory: MemoryWrite) -> int | None:
    source = _coerce_source(memory)
    if source is None:
        return None
    return source.chunk_index


def _coerce_source(memory: MemoryWrite) -> MemorySource | None:
    source = memory.source
    if isinstance(source, MemorySource):
        return source
    if isinstance(source, Mapping):
        return MemorySource(**dict(source))
    return None