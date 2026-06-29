"""Memory gateway contracts and normalized memory payloads."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from app.contracts.context import OrchestrationContext

MemoryLookupKind = Literal["memory", "chunk"]


@dataclass(slots=True)
class MemorySource:
    """Normalized provenance information for one memory record."""

    source_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    source_uri: str | None = None
    source_hash: str | None = None
    chunk_index: int | None = None
    section_path: tuple[str, ...] = field(default_factory=tuple)
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source_id = _normalized_scope_text(self.source_id)
        self.document_id = _normalized_scope_text(self.document_id)
        self.chunk_id = _normalized_scope_text(self.chunk_id)
        self.source_uri = _normalized_scope_text(self.source_uri)
        self.source_hash = _normalized_scope_text(self.source_hash)
        self.title = _normalized_scope_text(self.title)
        self.section_path = _normalize_text_tuple(self.section_path)
        self.metadata = _copy_mapping(self.metadata)


@dataclass(slots=True)
class MemoryScope:
    """Logical scope applied to memory reads and writes."""

    user_id: str | None = None
    project_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None
    agent_name: str | None = None
    usecase: str | None = None
    source_id: str | None = None
    document_id: str | None = None
    tags: tuple[str, ...] | list[str] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.user_id = _normalized_scope_text(self.user_id)
        self.project_id = _normalized_scope_text(self.project_id)
        self.tenant_id = _normalized_scope_text(self.tenant_id)
        self.session_id = _normalized_scope_text(self.session_id)
        self.agent_name = _normalized_scope_text(self.agent_name)
        self.usecase = _normalized_scope_text(self.usecase)
        self.source_id = _normalized_scope_text(self.source_id)
        self.document_id = _normalized_scope_text(self.document_id)
        self.tags = _normalize_text_tuple(self.tags)
        self.metadata = _copy_mapping(self.metadata)

    def normalized(self) -> MemoryScope:
        """Return a copy with empty strings removed from scope fields."""

        return MemoryScope(
            user_id=self.user_id,
            project_id=self.project_id,
            tenant_id=self.tenant_id,
            session_id=self.session_id,
            agent_name=self.agent_name,
            usecase=self.usecase,
            source_id=self.source_id,
            document_id=self.document_id,
            tags=self.tags,
            metadata=self.metadata,
        )

    def has_explicit_scope(self) -> bool:
        """Report whether any scope dimension is present."""

        scope = self.normalized()
        return any(
            (
                scope.user_id,
                scope.project_id,
                scope.tenant_id,
                scope.session_id,
                scope.agent_name,
                scope.usecase,
                scope.source_id,
                scope.document_id,
                scope.tags,
            )
        )

    def has_durable_scope(self) -> bool:
        """Report whether one durable long-term scope is present."""

        scope = self.normalized()
        return any(
            (
                scope.user_id,
                scope.project_id,
                scope.tenant_id,
                scope.source_id,
                scope.document_id,
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
        elif scope.source_id and scope.document_id:
            scope_type = "document"
        elif scope.source_id:
            scope_type = "source"
        elif scope.agent_name:
            scope_type = "agent"
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
            "session_id_present": scope.session_id is not None,
            "agent_name_present": scope.agent_name is not None,
            "usecase_present": scope.usecase is not None,
            "source_id_present": scope.source_id is not None,
            "document_id_present": scope.document_id is not None,
            "tag_count": len(scope.tags),
        }


MemoryScopes = MemoryScope


@dataclass(slots=True)
class MemorySearchFilters:
    """Safe, bounded filters for public memory search operations."""

    kinds: tuple[str, ...] | list[str] = field(default_factory=tuple)
    tags: tuple[str, ...] | list[str] = field(default_factory=tuple)
    status: tuple[str, ...] | list[str] = field(default_factory=lambda: ("active",))
    source_ids: tuple[str, ...] | list[str] = field(default_factory=tuple)
    document_ids: tuple[str, ...] | list[str] = field(default_factory=tuple)
    created_after: str | None = None
    created_before: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.kinds = _normalize_text_tuple(self.kinds)
        self.tags = _normalize_text_tuple(self.tags)
        self.status = _normalize_text_tuple(self.status)
        self.source_ids = _normalize_text_tuple(self.source_ids)
        self.document_ids = _normalize_text_tuple(self.document_ids)
        self.created_after = _normalized_scope_text(self.created_after)
        self.created_before = _normalized_scope_text(self.created_before)
        self.metadata = _copy_mapping(self.metadata)


@dataclass(slots=True)
class MemorySearchRequest:
    """Normalized request for memory retrieval."""

    text: str
    scope: MemoryScope
    memory_types: list[str] | tuple[str, ...] | None = None
    limit: int | None = 10
    include_document_chunks: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    filters: MemorySearchFilters | Mapping[str, Any] | None = None
    candidate_k: int | None = None
    include_agent_memories: bool = True
    include_graph_context: bool = True
    max_result_chars: int | None = None
    query_id: str | None = None
    top_k: int | None = None

    def __post_init__(self) -> None:
        self.text = self.text.strip()
        if self.text == "":
            raise ValueError("Memory search text must not be empty.")
        self.scope = _coerce_scope(self.scope)
        self.metadata = _copy_mapping(self.metadata)
        self.query_id = _normalized_scope_text(self.query_id)
        if self.memory_types is not None:
            normalized_types = [
                item
                for item in (_normalized_scope_text(value) for value in self.memory_types)
                if item is not None
            ]
            self.memory_types = normalized_types or None
        if isinstance(self.filters, Mapping):
            self.filters = MemorySearchFilters(**dict(self.filters))
        if self.top_k is None and self.limit is not None:
            self.top_k = self.limit
        elif self.limit is None and self.top_k is not None:
            self.limit = self.top_k
        if self.limit is None:
            self.limit = 10
        if self.top_k is None:
            self.top_k = self.limit

    @property
    def query(self) -> str:
        return self.text

    @property
    def scopes(self) -> MemoryScope:
        return self.scope


@dataclass(slots=True)
class MemoryScore:
    """Normalized score breakdown for one search hit."""

    final_score: float | None = None
    vector_score: float | None = None
    bm25_score: float | None = None
    reranker_score: float | None = None
    temporal_score: float | None = None
    importance_score: float | None = None
    user_rating_score: float | None = None
    graph_score: float | None = None
    component_scores: dict[str, float] = field(default_factory=dict)
    normalized_scores: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.component_scores = {
            str(name): float(score)
            for name, score in self.component_scores.items()
            if isinstance(score, (int, float))
        }
        self.normalized_scores = {
            str(name): float(score)
            for name, score in self.normalized_scores.items()
            if isinstance(score, (int, float))
        }
        self.metadata = _copy_mapping(self.metadata)


@dataclass(slots=True)
class MemoryRecord:
    """Persisted memory record returned by the gateway."""

    memory_id: str
    text: str
    memory_type: str
    scope: MemoryScope
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "active"
    source: MemorySource | Mapping[str, Any] | None = None
    importance: float | None = None
    confidence: float | None = None
    created_at: str | None = None
    updated_at: str | None = None
    expires_at: str | None = None
    tags: tuple[str, ...] | list[str] = field(default_factory=tuple)
    title: str | None = None
    summary: str | None = None

    def __post_init__(self) -> None:
        self.memory_id = self.memory_id.strip()
        if self.memory_id == "":
            raise ValueError("Memory record ID must not be empty.")
        self.text = self.text.strip()
        if self.text == "":
            raise ValueError("Memory record text must not be empty.")
        self.memory_type = self.memory_type.strip()
        if self.memory_type == "":
            raise ValueError("Memory record type must not be empty.")
        self.scope = _coerce_scope(self.scope)
        self.metadata = _copy_mapping(self.metadata)
        self.status = _normalized_scope_text(self.status) or "active"
        self.tags = _normalize_text_tuple(self.tags)
        self.title = _normalized_scope_text(self.title)
        self.summary = _normalized_scope_text(self.summary)
        if isinstance(self.source, Mapping):
            self.source = MemorySource(**dict(self.source))

    @property
    def kind(self) -> str:
        return self.memory_type

    @property
    def content(self) -> str:
        return self.text

    @property
    def scopes(self) -> MemoryScope:
        return self.scope

    @property
    def source_id(self) -> str | None:
        if isinstance(self.source, MemorySource):
            return self.source.source_id
        if isinstance(self.source, Mapping):
            return _normalized_scope_text(self.source.get("source_id"))
        return None

    @property
    def document_id(self) -> str | None:
        if isinstance(self.source, MemorySource):
            return self.source.document_id
        if isinstance(self.source, Mapping):
            return _normalized_scope_text(self.source.get("document_id"))
        return None

    @property
    def chunk_id(self) -> str | None:
        if isinstance(self.source, MemorySource):
            return self.source.chunk_id
        if isinstance(self.source, Mapping):
            return _normalized_scope_text(self.source.get("chunk_id"))
        return None


@dataclass(slots=True)
class MemoryResult:
    """Single logical memory search hit with legacy field compatibility."""

    memory_id: str
    text: str
    score: float | None = None
    memory_type: str | None = None
    source_id: str | None = None
    chunk_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    record: MemoryRecord | Mapping[str, Any] | None = None
    score_details: MemoryScore | None = None
    match_reason: str | None = None
    highlights: list[str] = field(default_factory=list)
    related_records: list[MemoryRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.memory_id = self.memory_id.strip()
        if self.memory_id == "":
            raise ValueError("Memory result ID must not be empty.")
        self.text = self.text.strip()
        if self.text == "":
            raise ValueError("Memory result text must not be empty.")
        self.memory_type = _normalized_scope_text(self.memory_type)
        self.source_id = _normalized_scope_text(self.source_id)
        self.chunk_id = _normalized_scope_text(self.chunk_id)
        self.metadata = _copy_mapping(self.metadata)
        self.highlights = [item for item in self.highlights if isinstance(item, str)]
        self.related_records = list(self.related_records)
        self.record = _coerce_record(
            self.record,
            memory_id=self.memory_id,
            text=self.text,
            memory_type=self.memory_type,
            source_id=self.source_id,
            chunk_id=self.chunk_id,
            metadata=self.metadata,
        )
        self.memory_id = self.record.memory_id
        self.text = self.record.text
        self.memory_type = self.record.memory_type
        self.source_id = self.record.source_id
        self.chunk_id = self.record.chunk_id
        if self.score_details is None and self.score is not None:
            self.score_details = MemoryScore(final_score=self.score)
        elif self.score_details is not None and self.score is None:
            self.score = self.score_details.final_score

    @property
    def kind(self) -> str | None:
        return self.memory_type

    @classmethod
    def from_record(
        cls,
        record: MemoryRecord,
        *,
        score: float | None = None,
        score_details: MemoryScore | None = None,
        match_reason: str | None = None,
        highlights: Sequence[str] = (),
        related_records: Sequence[MemoryRecord] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> MemoryResult:
        return cls(
            memory_id=record.memory_id,
            text=record.text,
            score=score,
            memory_type=record.memory_type,
            source_id=record.source_id,
            chunk_id=record.chunk_id,
            metadata=(dict(record.metadata) if metadata is None else _copy_mapping(metadata)),
            record=record,
            score_details=score_details,
            match_reason=match_reason,
            highlights=list(highlights),
            related_records=list(related_records),
        )


MemorySearchHit = MemoryResult


@dataclass(slots=True)
class MemorySearchResult:
    """Normalized public search response."""

    results: list[MemoryResult] = field(default_factory=list)
    query_id: str | None = None
    total_candidates: int | None = None
    search_strategy: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.results = list(self.results)
        self.query_id = _normalized_scope_text(self.query_id)
        self.search_strategy = _normalized_scope_text(self.search_strategy)
        self.metadata = _copy_mapping(self.metadata)
        if self.total_candidates is None:
            self.total_candidates = len(self.results)

    def __iter__(self) -> Iterator[MemoryResult]:
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)

    def __getitem__(self, index: int) -> MemoryResult:
        return self.results[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, MemorySearchResult):
            return (
                self.results == other.results
                and self.query_id == other.query_id
                and self.total_candidates == other.total_candidates
                and self.search_strategy == other.search_strategy
                and self.metadata == other.metadata
            )
        if isinstance(other, list):
            return self.results == other
        return False


@dataclass(slots=True)
class MemoryChunkContextRequest:
    """Normalized request for a chunk window around one document chunk."""

    chunk_id: str
    scope: MemoryScope = field(default_factory=MemoryScope)
    before: int = 0
    after: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.chunk_id = self.chunk_id.strip()
        if self.chunk_id == "":
            raise ValueError("Chunk-context requests require a chunk ID.")
        self.scope = _coerce_scope(self.scope)
        if self.before < 0 or self.after < 0:
            raise ValueError("Chunk-context window sizes must be non-negative.")
        self.metadata = _copy_mapping(self.metadata)

    @property
    def scopes(self) -> MemoryScope:
        return self.scope


@dataclass(slots=True)
class MemoryChunkContextResult:
    """Normalized chunk window surrounding one document chunk."""

    chunk: MemoryResult
    before: list[MemoryResult] = field(default_factory=list)
    after: list[MemoryResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.chunk = _coerce_result(self.chunk)
        self.before = [_coerce_result(item) for item in self.before]
        self.after = [_coerce_result(item) for item in self.after]
        self.metadata = _copy_mapping(self.metadata)

    @property
    def ordered_results(self) -> tuple[MemoryResult, ...]:
        return (*self.before, self.chunk, *self.after)

    @property
    def included_memory_ids(self) -> tuple[str, ...]:
        return tuple(result.memory_id for result in self.ordered_results)


@dataclass(slots=True)
class MemoryPromptContext:
    """Bounded prompt-context payload assembled from memory hits."""

    text: str = ""
    included_memory_ids: tuple[str, ...] | list[str] = field(default_factory=tuple)
    omitted_memory_ids: tuple[str, ...] | list[str] = field(default_factory=tuple)
    total_chars: int | None = None
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.included_memory_ids = _normalize_text_tuple(self.included_memory_ids)
        self.omitted_memory_ids = _normalize_text_tuple(self.omitted_memory_ids)
        self.metadata = _copy_mapping(self.metadata)
        if self.total_chars is None:
            self.total_chars = len(self.text)

    def __bool__(self) -> bool:
        return self.text != ""


@dataclass(slots=True)
class MemoryWrite:
    """Normalized write request for long-term memory."""

    text: str
    scope: MemoryScope
    memory_type: str
    stable_key: str | None = None
    importance: float | None = None
    confidence: float | None = None
    ttl_days: int | None = None
    tags: tuple[str, ...] | list[str] = field(default_factory=tuple)
    source: MemorySource | Mapping[str, Any] | None = None
    allow_retrieval: bool | None = None
    allow_llm_context: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.text = self.text.strip()
        if self.text == "":
            raise ValueError("Memory write text must not be empty.")
        self.scope = _coerce_scope(self.scope)
        self.memory_type = self.memory_type.strip()
        if self.memory_type == "":
            raise ValueError("Memory write type must not be empty.")
        self.stable_key = _normalized_scope_text(self.stable_key)
        self.tags = _normalize_text_tuple(self.tags)
        if isinstance(self.source, Mapping):
            self.source = MemorySource(**dict(self.source))
        self.metadata = _copy_mapping(self.metadata)

    @property
    def kind(self) -> str:
        return self.memory_type

    @property
    def content(self) -> str:
        return self.text

    @property
    def scopes(self) -> MemoryScope:
        return self.scope


MemoryUpsertRequest = MemoryWrite


@dataclass(slots=True)
class MemoryGetRequest:
    """Normalized single-record or single-chunk lookup request."""

    identifier: str
    scope: MemoryScope = field(default_factory=MemoryScope)
    lookup_kind: MemoryLookupKind = "memory"
    include_related: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.identifier = self.identifier.strip()
        if self.identifier == "":
            raise ValueError("Memory get identifier must not be empty.")
        self.scope = _coerce_scope(self.scope)
        self.metadata = _copy_mapping(self.metadata)

    @property
    def memory_id(self) -> str:
        return self.identifier

    @property
    def scopes(self) -> MemoryScope:
        return self.scope


@dataclass(slots=True)
class MemoryLifecycleRequest:
    """Lifecycle update request for one memory record."""

    memory_id: str
    scope: MemoryScope = field(default_factory=MemoryScope)
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.memory_id = self.memory_id.strip()
        if self.memory_id == "":
            raise ValueError("Memory lifecycle request requires a memory ID.")
        self.scope = _coerce_scope(self.scope)
        self.reason = _normalized_scope_text(self.reason)
        self.metadata = _copy_mapping(self.metadata)

    @property
    def scopes(self) -> MemoryScope:
        return self.scope


@dataclass(slots=True)
class MemorySupersedeRequest:
    """Lifecycle request that replaces one memory with another."""

    old_memory_id: str
    new_memory_id: str
    scope: MemoryScope = field(default_factory=MemoryScope)
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.old_memory_id = self.old_memory_id.strip()
        self.new_memory_id = self.new_memory_id.strip()
        if self.old_memory_id == "" or self.new_memory_id == "":
            raise ValueError("Memory supersede requests require both old and new IDs.")
        self.scope = _coerce_scope(self.scope)
        self.reason = _normalized_scope_text(self.reason)
        self.metadata = _copy_mapping(self.metadata)

    @property
    def scopes(self) -> MemoryScope:
        return self.scope


@dataclass(slots=True)
class MemoryContradictRequest:
    """Lifecycle request that marks two memories as conflicting."""

    memory_id_a: str
    memory_id_b: str
    scope: MemoryScope = field(default_factory=MemoryScope)
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.memory_id_a = self.memory_id_a.strip()
        self.memory_id_b = self.memory_id_b.strip()
        if self.memory_id_a == "" or self.memory_id_b == "":
            raise ValueError("Memory contradict requests require both memory IDs.")
        self.scope = _coerce_scope(self.scope)
        self.reason = _normalized_scope_text(self.reason)
        self.metadata = _copy_mapping(self.metadata)

    @property
    def scopes(self) -> MemoryScope:
        return self.scope


@dataclass(slots=True)
class MemoryForgetRequest:
    """Deletion or tombstone request for one memory record."""

    memory_id: str
    scope: MemoryScope = field(default_factory=MemoryScope)
    reason: str | None = None
    hard_delete: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.memory_id = self.memory_id.strip()
        if self.memory_id == "":
            raise ValueError("Memory forget requests require a memory ID.")
        self.scope = _coerce_scope(self.scope)
        self.reason = _normalized_scope_text(self.reason)
        self.metadata = _copy_mapping(self.metadata)

    @property
    def scopes(self) -> MemoryScope:
        return self.scope


@dataclass(slots=True)
class DocumentIngestRequest:
    """Public request to ingest one source document into long-term memory."""

    source_id: str
    scope: MemoryScope
    document_id: str | None = None
    content: str | None = None
    path: str | None = None
    source_uri: str | None = None
    source_hash: str | None = None
    title: str | None = None
    content_type: str = "text/markdown"
    replace_existing: bool = True
    mark_missing_chunks_removed: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source_id = self.source_id.strip()
        if self.source_id == "":
            raise ValueError("Document ingestion requires a source ID.")
        self.scope = _coerce_scope(self.scope)
        self.document_id = _normalized_scope_text(self.document_id)
        self.content = _normalized_document_text(self.content)
        self.path = _normalized_scope_text(self.path)
        self.source_uri = _normalized_scope_text(self.source_uri)
        self.source_hash = _normalized_scope_text(self.source_hash)
        self.title = _normalized_scope_text(self.title)
        self.content_type = self.content_type.strip() or "text/markdown"
        self.metadata = _copy_mapping(self.metadata)
        if self.content is None and self.path is None:
            raise ValueError("Document ingestion requires either inline content or a path.")

    @property
    def scopes(self) -> MemoryScope:
        return self.scope


@dataclass(slots=True)
class MemoryDeleteByScopeRequest:
    """Public request to delete or tombstone memories by scope."""

    scope: MemoryScope
    hard_delete: bool = False
    require_confirmation: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.scope = _coerce_scope(self.scope)
        self.metadata = _copy_mapping(self.metadata)

    @property
    def scopes(self) -> MemoryScope:
        return self.scope


@dataclass(slots=True)
class MemoryExportByScopeRequest:
    """Public request to export memories by scope."""

    scope: MemoryScope
    include_content: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.scope = _coerce_scope(self.scope)
        self.metadata = _copy_mapping(self.metadata)

    @property
    def scopes(self) -> MemoryScope:
        return self.scope


@dataclass(slots=True)
class MemoryWriteResult:
    """Normalized write or lifecycle result."""

    operation: str
    status: str
    record: MemoryRecord | None = None
    changed: bool = True
    affected_ids: tuple[str, ...] | list[str] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.operation = self.operation.strip()
        if self.operation == "":
            raise ValueError("Memory write results require an operation name.")
        self.status = self.status.strip() or "ok"
        self.affected_ids = _normalize_text_tuple(self.affected_ids)
        self.metadata = _copy_mapping(self.metadata)

    @property
    def memory_id(self) -> str | None:
        if self.record is not None:
            return self.record.memory_id
        if self.affected_ids:
            return self.affected_ids[0]
        return None

    @property
    def text(self) -> str | None:
        return self.record.text if self.record is not None else None

    @property
    def memory_type(self) -> str | None:
        return self.record.memory_type if self.record is not None else None

    @property
    def scope(self) -> MemoryScope | None:
        return self.record.scope if self.record is not None else None


@dataclass(slots=True)
class DocumentIngestResult:
    """Normalized result for one document-ingestion operation."""

    source_id: str
    document_id: str | None
    source_hash: str | None
    status: str
    chunks_created: int = 0
    chunks_updated: int = 0
    chunks_unchanged: int = 0
    chunks_removed: int = 0
    skipped_unchanged_document: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source_id = self.source_id.strip()
        self.document_id = _normalized_scope_text(self.document_id)
        self.source_hash = _normalized_scope_text(self.source_hash)
        self.status = self.status.strip() or "completed"
        self.metadata = _copy_mapping(self.metadata)


@dataclass(slots=True)
class MemoryDeleteResult:
    """Normalized result for privacy deletion by scope."""

    scope: MemoryScope
    deleted_count: int
    hard_delete: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.scope = _coerce_scope(self.scope)
        self.metadata = _copy_mapping(self.metadata)


@dataclass(slots=True)
class MemoryExportResult:
    """Normalized export result for privacy/data-portability flows."""

    scope: MemoryScope
    records: list[MemoryRecord] = field(default_factory=list)
    exported_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.scope = _coerce_scope(self.scope)
        self.records = list(self.records)
        self.exported_at = _normalized_scope_text(self.exported_at)
        self.metadata = _copy_mapping(self.metadata)

    @property
    def record_count(self) -> int:
        return len(self.records)


@dataclass(slots=True)
class MemoryHealthResult(Mapping[str, Any]):
    """Safe health summary for the public memory surface."""

    status: str
    enabled: bool
    provider: str
    configured: bool
    required: bool = False
    schema_initialized: bool | None = None
    embedding_model_configured: bool | None = None
    embedding_dimension: int | None = None
    search_available: bool | None = None
    ingest_available: bool | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.status = self.status.strip() or "unknown"
        self.provider = self.provider.strip() or "unknown"
        self.error = _normalized_scope_text(self.error)
        self.metadata = _copy_mapping(self.metadata)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "enabled": self.enabled,
            "provider": self.provider,
            "configured": self.configured,
            "required": self.required,
            "schema_initialized": self.schema_initialized,
            "embedding_model_configured": self.embedding_model_configured,
            "embedding_dimension": self.embedding_dimension,
            "search_available": self.search_available,
            "ingest_available": self.ingest_available,
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())


@dataclass(slots=True)
class MemoryStatsResult(Mapping[str, Any]):
    """Safe stats summary for the public memory surface."""

    total_records: int = 0
    scope_counts: dict[str, int] = field(default_factory=dict)
    status_counts: dict[str, int] = field(default_factory=dict)
    type_counts: dict[str, int] = field(default_factory=dict)
    status: str = "ok"
    provider: str | None = None
    configured: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.scope_counts = _normalize_int_mapping(self.scope_counts)
        self.status_counts = _normalize_int_mapping(self.status_counts)
        self.type_counts = _normalize_int_mapping(self.type_counts)
        self.status = self.status.strip() or "ok"
        self.provider = _normalized_scope_text(self.provider)
        self.metadata = _copy_mapping(self.metadata)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_records": self.total_records,
            "scope_counts": dict(self.scope_counts),
            "status_counts": dict(self.status_counts),
            "type_counts": dict(self.type_counts),
            "status": self.status,
            "provider": self.provider,
            "configured": self.configured,
            "metadata": dict(self.metadata),
        }

    def __iter__(self) -> Iterator[str]:
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]


class MemoryGateway(Protocol):
    """Provider-neutral memory access used by orchestration code."""

    async def search(
        self,
        request: MemorySearchRequest,
        context: OrchestrationContext,
    ) -> MemorySearchResult:
        ...

    async def get(
        self,
        request: MemoryGetRequest,
        context: OrchestrationContext,
    ) -> MemoryRecord | None:
        ...

    async def get_chunk_context(
        self,
        request: MemoryChunkContextRequest,
        context: OrchestrationContext,
    ) -> MemoryChunkContextResult | None:
        ...

    async def upsert(
        self,
        memory: MemoryWrite,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        ...

    async def promote(
        self,
        request: MemoryLifecycleRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        ...

    async def supersede(
        self,
        request: MemorySupersedeRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        ...

    async def contradict(
        self,
        request: MemoryContradictRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        ...

    async def expire(
        self,
        request: MemoryLifecycleRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        ...

    async def forget(
        self,
        request: MemoryForgetRequest,
        context: OrchestrationContext,
    ) -> MemoryWriteResult:
        ...

    async def ingest_document(
        self,
        request: DocumentIngestRequest,
        context: OrchestrationContext,
    ) -> DocumentIngestResult:
        ...

    async def delete_by_scope(
        self,
        request: MemoryDeleteByScopeRequest,
        context: OrchestrationContext,
    ) -> MemoryDeleteResult:
        ...

    async def export_by_scope(
        self,
        request: MemoryExportByScopeRequest,
        context: OrchestrationContext,
    ) -> MemoryExportResult:
        ...

    async def health(self) -> MemoryHealthResult:
        ...

    async def stats(
        self,
        scopes: MemoryScope | None = None,
        context: OrchestrationContext | None = None,
    ) -> MemoryStatsResult:
        ...


def _coerce_scope(value: MemoryScope | Mapping[str, Any]) -> MemoryScope:
    if isinstance(value, MemoryScope):
        return value.normalized()
    if isinstance(value, Mapping):
        return MemoryScope(**dict(value))
    raise TypeError("Memory scope values must be MemoryScope instances or mappings.")


def _coerce_record(
    value: MemoryRecord | Mapping[str, Any] | None,
    *,
    memory_id: str,
    text: str,
    memory_type: str | None,
    source_id: str | None,
    chunk_id: str | None,
    metadata: Mapping[str, Any],
) -> MemoryRecord:
    if isinstance(value, MemoryRecord):
        return value
    if isinstance(value, Mapping):
        return MemoryRecord(**dict(value))
    return MemoryRecord(
        memory_id=memory_id,
        text=text,
        memory_type=memory_type or "observation",
        scope=MemoryScope(),
        metadata=dict(metadata),
        source=(
            MemorySource(source_id=source_id, chunk_id=chunk_id)
            if source_id is not None or chunk_id is not None
            else None
        ),
    )


def _coerce_result(
    value: MemoryResult | MemoryRecord | Mapping[str, Any],
) -> MemoryResult:
    if isinstance(value, MemoryResult):
        return value
    if isinstance(value, MemoryRecord):
        return MemoryResult.from_record(value)
    if isinstance(value, Mapping):
        return MemoryResult(**dict(value))
    raise TypeError("Memory result values must be MemoryResult, MemoryRecord, or mappings.")


def _normalized_document_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Document content must be a string when provided.")
    stripped = value.strip()
    return stripped or None


def _normalize_int_mapping(value: Mapping[str, Any]) -> dict[str, int]:
    return {
        str(key): int(item)
        for key, item in value.items()
        if isinstance(item, int)
    }


def _copy_mapping(value: Mapping[str, Any] | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _normalize_text_tuple(values: Sequence[str] | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized = [_normalized_scope_text(value) for value in values]
    return tuple(item for item in normalized if item is not None)


def _normalized_scope_text(value: str | None) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None