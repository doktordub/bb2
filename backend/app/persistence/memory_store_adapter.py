"""Backend-local adapter for the external memory_store package."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.contracts.health import HEALTH_DEGRADED, HEALTH_FAILED, HEALTH_OK
from app.contracts.memory import MemoryRecord, MemoryResult, MemoryScope, MemorySearchRequest, MemoryWrite
from app.contracts.trace import MEMORY_SEARCH_COMPLETED, MEMORY_SEARCH_STARTED, TraceEvent
from app.observability.events import (
    MEMORY_UPSERT_COMPLETED,
    MEMORY_UPSERT_FAILED,
    MEMORY_UPSERT_STARTED,
)
from app.persistence.errors import MemoryGatewayError
from app.persistence.settings import MemoryStoreSettings

if TYPE_CHECKING:
    from app.contracts.context import OrchestrationContext


_NON_DOCUMENT_MEMORY_TYPES = (
    "user_preference",
    "project_fact",
    "task_state",
    "conversation_summary",
    "decision",
    "observation",
    "error_debug_note",
)


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


class MemoryStoreAdapter:
    """Async backend adapter around the sync memory_store service."""

    def __init__(self, settings: MemoryStoreSettings, *, required: bool) -> None:
        self._settings = settings
        self._required = required
        self._runtime: _MemoryStoreRuntime | None = None
        self._service: Any | None = None
        self._initialization_error: Exception | None = None
        self._initialization_lock = asyncio.Lock()

    async def initialize(self) -> None:
        await self._ensure_service()

    async def close(self) -> None:
        service = self._service
        self._service = None
        if service is None:
            return

        close = getattr(service, "close", None)
        if callable(close):
            await asyncio.to_thread(close)

    async def search(
        self,
        request: MemorySearchRequest,
        context: OrchestrationContext,
    ) -> list[MemoryResult]:
        if not isinstance(request.text, str) or request.text.strip() == "":
            raise MemoryGatewayError("Memory search requires non-empty text.")

        scope = self._resolve_scope(request.scope, context)
        limit = normalize_memory_search_limit(
            request.limit,
            default_limit=self._settings.search_limit_default,
            max_limit=self._settings.search_limit_max,
        )

        try:
            runtime = self._get_runtime()
            query = runtime.MemorySearchQuery(
                text=request.text,
                scope=self._to_store_scope(runtime, scope),
                limit=limit,
                memory_types=_normalize_memory_types(request),
                allow_retrieval_only=True,
            )
            await self._record_trace(
                context,
                event_type=MEMORY_SEARCH_STARTED,
                payload={
                    **scope.summary(),
                    "limit": limit,
                    "include_document_chunks": request.include_document_chunks,
                    "memory_type_count": len(query.memory_types or []),
                },
            )
            service = await self._ensure_service()
            raw_results = await asyncio.to_thread(service.search, query)
        except Exception as exc:
            await self._record_trace(
                context,
                event_type=MEMORY_SEARCH_COMPLETED,
                payload={
                    **scope.summary(),
                    "limit": limit,
                    "result_count": 0,
                    "success": False,
                    "error_type": type(exc).__name__,
                },
            )
            raise MemoryGatewayError("Memory search failed.") from exc

        results = [self._map_search_result(item) for item in raw_results]
        await self._record_trace(
            context,
            event_type=MEMORY_SEARCH_COMPLETED,
            payload={
                **scope.summary(),
                "limit": limit,
                "result_count": len(results),
                "success": True,
            },
        )
        return results

    async def upsert(
        self,
        memory: MemoryWrite,
        context: OrchestrationContext,
    ) -> MemoryRecord:
        if not self._settings.allow_writes:
            await self._record_trace(
                context,
                event_type=MEMORY_UPSERT_FAILED,
                payload={
                    **memory.scope.normalized().summary(),
                    "memory_type": memory.memory_type,
                    "stable_key_present": memory.stable_key is not None,
                    "success": False,
                    "reason": "writes_disabled",
                },
            )
            raise MemoryGatewayError("Memory writes are disabled by configuration.")

        scope = self._resolve_scope(memory.scope, context)

        try:
            runtime = self._get_runtime()
            create = runtime.MemoryCreate(
                text=memory.text,
                scope=self._to_store_scope(runtime, scope),
                memory_type=memory.memory_type,
                importance=memory.importance if memory.importance is not None else 0.5,
                metadata=dict(memory.metadata),
            )
            await self._record_trace(
                context,
                event_type=MEMORY_UPSERT_STARTED,
                payload={
                    **scope.summary(),
                    "memory_type": memory.memory_type,
                    "stable_key_present": memory.stable_key is not None,
                },
            )
            service = await self._ensure_service()
            record = await asyncio.to_thread(
                self._upsert_memory_sync,
                service,
                create,
                memory.stable_key,
            )
        except Exception as exc:
            await self._record_trace(
                context,
                event_type=MEMORY_UPSERT_FAILED,
                payload={
                    **scope.summary(),
                    "memory_type": memory.memory_type,
                    "stable_key_present": memory.stable_key is not None,
                    "success": False,
                    "error_type": type(exc).__name__,
                },
            )
            raise MemoryGatewayError("Memory upsert failed.") from exc

        mapped = self._map_record(record, scope=scope)
        await self._record_trace(
            context,
            event_type=MEMORY_UPSERT_COMPLETED,
            payload={
                **scope.summary(),
                "memory_type": mapped.memory_type,
                "memory_id_present": True,
                "stable_key_present": memory.stable_key is not None,
                "success": True,
            },
        )
        return mapped

    async def forget(self, memory_id: str, context: OrchestrationContext) -> None:
        if not self._settings.allow_writes:
            raise MemoryGatewayError("Memory writes are disabled by configuration.")
        if not isinstance(memory_id, str) or memory_id.strip() == "":
            raise MemoryGatewayError("Memory forget requires a non-empty memory ID.")

        try:
            service = await self._ensure_service()
            await asyncio.to_thread(service.forget, memory_id.strip())
        except Exception as exc:
            raise MemoryGatewayError("Memory forget failed.") from exc

    async def health(self) -> dict[str, Any]:
        base = {
            "configured": True,
            "provider": "memory_store",
            "required": self._required,
            "config_path_configured": self._settings.config_path is not None,
            "database_path_configured": self._settings.database_path is not None,
            "service_initialized": self._service is not None,
        }

        config_issue = self._configuration_issue()
        if config_issue is not None:
            reason, error_type = config_issue
            return {
                **base,
                "status": self._problem_status(),
                "reason": reason,
                "error_type": error_type,
            }

        try:
            runtime = self._get_runtime()
        except Exception as exc:
            return {
                **base,
                "status": self._problem_status(),
                "reason": "dependency_unavailable",
                "error_type": type(exc).__name__,
            }

        payload: dict[str, Any] = {
            **base,
            "status": HEALTH_OK,
            "dependency_available": runtime is not None,
        }

        if self._service is not None:
            try:
                raw_health = await asyncio.to_thread(self._service.health)
            except Exception as exc:
                return {
                    **base,
                    "status": self._problem_status(),
                    "reason": "health_check_failed",
                    "error_type": type(exc).__name__,
                }

            dependencies = getattr(raw_health, "dependencies", None)
            if isinstance(dependencies, Mapping):
                payload["dependencies"] = {
                    str(name): bool(value) for name, value in dependencies.items()
                }

            schema_version = getattr(raw_health, "schema_version", None)
            if isinstance(schema_version, int):
                payload["schema_version"] = schema_version

        if self._initialization_error is not None:
            return {
                **base,
                "status": self._problem_status(),
                "reason": "initialization_failed",
                "error_type": type(self._initialization_error).__name__,
            }

        return payload

    def _get_runtime(self) -> _MemoryStoreRuntime:
        if self._runtime is None:
            self._runtime = _load_memory_store_runtime()
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
        runtime = self._get_runtime()
        overrides: dict[str, Any] = {}
        if self._settings.database_path is not None:
            overrides["database"] = {"path": str(self._settings.database_path)}

        if self._settings.config_path is not None:
            return runtime.MemoryService.from_config(self._settings.config_path, **overrides)

        return runtime.MemoryService.from_config(None, **overrides)

    def _resolve_scope(
        self,
        scope: MemoryScope,
        context: OrchestrationContext,
    ) -> MemoryScope:
        normalized = scope.normalized()
        if normalized.user_id is not None or normalized.project_id is not None:
            return normalized

        if self._settings.default_scope == "user":
            fallback_user_id = _optional_text(context.request.user_id)
            if fallback_user_id is not None:
                return MemoryScope(
                    user_id=fallback_user_id,
                    project_id=normalized.project_id,
                    tenant_id=normalized.tenant_id,
                    usecase=normalized.usecase,
                    session_id=normalized.session_id,
                    metadata=dict(normalized.metadata),
                )

        if self._settings.default_scope == "project":
            project_id = _optional_text(context.request.metadata.get("project_id"))
            if project_id is None:
                project_id = _optional_text(context.runtime_metadata.get("project_id"))
            if project_id is not None:
                return MemoryScope(
                    user_id=normalized.user_id,
                    project_id=project_id,
                    tenant_id=normalized.tenant_id,
                    usecase=normalized.usecase,
                    session_id=normalized.session_id,
                    metadata=dict(normalized.metadata),
                )

        raise MemoryGatewayError(
            "Memory operations require an explicit user_id or project_id scope."
        )

    def _to_store_scope(self, runtime: _MemoryStoreRuntime, scope: MemoryScope) -> Any:
        return runtime.Scope(
            user_id=scope.user_id,
            project_id=scope.project_id,
        )

    def _map_search_result(self, result: Any) -> MemoryResult:
        record = getattr(result, "record", getattr(result, "memory", None))
        if record is None:
            raise MemoryGatewayError("Memory search returned an invalid result record.")

        score = getattr(result, "final_score", None)
        return MemoryResult(
            memory_id=str(getattr(record, "memory_id")),
            text=str(getattr(record, "text")),
            score=float(score) if isinstance(score, (int, float)) else None,
            memory_type=_enum_or_text(getattr(record, "memory_type", None)),
            source_id=_first_text(
                getattr(record, "source_hash", None),
                getattr(record, "source_path", None),
                getattr(record, "source_uri", None),
                getattr(record, "stable_key", None),
            ),
            chunk_id=_optional_text(getattr(record, "chunk_id", None)),
            metadata=_copy_mapping(getattr(record, "metadata", None)),
        )

    def _map_record(self, record: Any, *, scope: MemoryScope) -> MemoryRecord:
        return MemoryRecord(
            memory_id=str(getattr(record, "memory_id")),
            text=str(getattr(record, "text")),
            memory_type=_enum_or_text(getattr(record, "memory_type", None)) or "observation",
            scope=scope,
            metadata=_copy_mapping(getattr(record, "metadata", None)),
        )

    def _configuration_issue(self) -> tuple[str, str] | None:
        config_path = self._settings.config_path
        if config_path is not None and not Path(config_path).exists():
            return ("config_path_missing", "FileNotFoundError")
        return None

    def _problem_status(self) -> str:
        return HEALTH_FAILED if self._required else HEALTH_DEGRADED

    def _upsert_memory_sync(self, service: Any, create: Any, stable_key: str | None) -> Any:
        return service.upsert_memory(create, stable_key=stable_key, embed=False)

    async def _record_trace(
        self,
        context: OrchestrationContext,
        *,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> None:
        try:
            await context.trace.record_event(
                TraceEvent(
                    trace_id=context.request.trace_id or "trace_memory",
                    session_id=context.request.session_id,
                    event_type=event_type,
                    component="app.persistence.memory_store_adapter",
                    timestamp=datetime.now(UTC),
                    user_id=context.request.user_id,
                    usecase=context.request.usecase,
                    payload=dict(payload),
                )
            )
        except Exception:
            return None


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


def _normalize_memory_types(request: MemorySearchRequest) -> list[str] | None:
    if request.memory_types:
        normalized = [_optional_text(item) for item in request.memory_types]
        result = [item for item in normalized if item is not None]
        if not request.include_document_chunks:
            result = [item for item in result if item != "document_chunk"]
        return result

    if not request.include_document_chunks:
        return list(_NON_DOCUMENT_MEMORY_TYPES)

    return None


def _copy_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


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