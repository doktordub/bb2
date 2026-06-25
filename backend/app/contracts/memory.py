"""Memory gateway contracts and normalized memory payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.contracts.context import OrchestrationContext


@dataclass(slots=True)
class MemoryScope:
    """Logical scope applied to memory reads and writes."""

    user_id: str | None = None
    project_id: str | None = None
    tenant_id: str | None = None
    usecase: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> MemoryScope:
        """Return a copy with empty strings removed from scope fields."""

        return MemoryScope(
            user_id=_normalized_scope_text(self.user_id),
            project_id=_normalized_scope_text(self.project_id),
            tenant_id=_normalized_scope_text(self.tenant_id),
            usecase=_normalized_scope_text(self.usecase),
            session_id=_normalized_scope_text(self.session_id),
            metadata=dict(self.metadata),
        )

    def has_explicit_scope(self) -> bool:
        """Report whether any scope dimension is present."""

        scope = self.normalized()
        return any(
            (
                scope.user_id,
                scope.project_id,
                scope.tenant_id,
                scope.usecase,
                scope.session_id,
            )
        )

    def summary(self) -> dict[str, Any]:
        """Return a trace-safe scope summary without raw identifiers."""

        scope = self.normalized()
        if scope.project_id and scope.user_id:
            scope_type = "project_user"
        elif scope.project_id:
            scope_type = "project"
        elif scope.user_id:
            scope_type = "user"
        elif scope.tenant_id:
            scope_type = "tenant"
        elif scope.usecase:
            scope_type = "usecase"
        elif scope.session_id:
            scope_type = "session"
        else:
            scope_type = "global"

        return {
            "scope_type": scope_type,
            "user_id_present": scope.user_id is not None,
            "project_id_present": scope.project_id is not None,
            "tenant_id_present": scope.tenant_id is not None,
            "usecase_present": scope.usecase is not None,
            "session_id_present": scope.session_id is not None,
        }


@dataclass(slots=True)
class MemorySearchRequest:
    """Normalized request for memory retrieval."""

    text: str
    scope: MemoryScope
    memory_types: list[str] | None = None
    limit: int = 10
    include_document_chunks: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryResult:
    """Single logical memory result."""

    memory_id: str
    text: str
    score: float | None = None
    memory_type: str | None = None
    source_id: str | None = None
    chunk_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryWrite:
    """Normalized write request for long-term memory."""

    text: str
    scope: MemoryScope
    memory_type: str
    stable_key: str | None = None
    importance: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryRecord:
    """Persisted memory record returned by the gateway."""

    memory_id: str
    text: str
    memory_type: str
    scope: MemoryScope
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryGateway(Protocol):
    """Provider-neutral memory access used by orchestration code."""

    async def search(
        self,
        request: MemorySearchRequest,
        context: OrchestrationContext,
    ) -> list[MemoryResult]:
        ...

    async def upsert(
        self,
        memory: MemoryWrite,
        context: OrchestrationContext,
    ) -> MemoryRecord:
        ...

    async def forget(self, memory_id: str, context: OrchestrationContext) -> None:
        ...

    async def health(self) -> dict[str, Any]:
        ...


def _normalized_scope_text(value: str | None) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None