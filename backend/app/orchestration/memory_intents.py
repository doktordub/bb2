"""Memory-intent helpers for retrieval and memory-update workflow strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any
from typing import Literal

from app.contracts.context import OrchestrationContext
from app.contracts.memory import MemoryRecord, MemoryResult, MemoryScope, MemorySearchRequest, MemorySearchResult
from app.orchestration.context_budget import BudgetedContext, ContextBudget, ContextBudgetItem, budget_context_items
from app.orchestration.models import MemorySearchSummary, sanitize_metadata
from app.orchestration.prompt_inputs import PromptSection

MemoryCandidateScope = Literal[
    "project_user",
    "project",
    "user",
    "tenant",
    "session",
    "agent",
    "usecase",
]

_ALLOWED_MEMORY_CANDIDATE_SCOPES: set[str] = {
    "project_user",
    "project",
    "user",
    "tenant",
    "session",
    "agent",
    "usecase",
}
_EXPLICIT_MEMORY_PATTERNS = (
    re.compile(r"^\s*(?:please\s+)?remember(?:\s+that)?\s+(?P<text>.+?)\s*$", re.IGNORECASE | re.DOTALL),
    re.compile(r"^\s*(?:save|store)\s+(?:this\s+)?(?:memory|fact|preference)?\s*:?[ \t]*(?P<text>.+?)\s*$", re.IGNORECASE | re.DOTALL),
)


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    """Bounded candidate for one durable memory write."""

    text: str
    memory_type: str = "user_fact"
    scope: MemoryCandidateScope = "project_user"
    importance: float | None = None
    confidence: float | None = None
    ttl_days: int | None = None
    reason: str | None = None
    stable_key: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    allow_retrieval: bool | None = None
    allow_llm_context: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _normalize_text(self.text))
        object.__setattr__(self, "memory_type", _normalize_text(self.memory_type))
        object.__setattr__(self, "scope", _normalize_candidate_scope(self.scope))
        object.__setattr__(self, "importance", _normalize_optional_float(self.importance))
        object.__setattr__(self, "confidence", _normalize_optional_float(self.confidence))
        object.__setattr__(self, "ttl_days", _normalize_optional_positive_int(self.ttl_days))
        object.__setattr__(self, "reason", _normalize_optional_text(self.reason))
        object.__setattr__(self, "stable_key", _normalize_optional_text(self.stable_key))
        object.__setattr__(self, "tags", _normalize_tags(self.tags))
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))

    @classmethod
    def from_mapping(cls, item: dict[str, Any]) -> "MemoryCandidate":
        return cls(
            text=item.get("text") or item.get("content") or item.get("value") or "",
            memory_type=item.get("memory_type") or item.get("type") or "user_fact",
            scope=_normalize_candidate_scope(item.get("scope")),
            importance=_normalize_optional_float(item.get("importance")),
            confidence=_normalize_optional_float(item.get("confidence")),
            ttl_days=_normalize_optional_positive_int(item.get("ttl_days")),
            reason=_normalize_optional_text(item.get("reason")),
            stable_key=_normalize_optional_text(item.get("stable_key")),
            tags=_normalize_tags(item.get("tags")),
            allow_retrieval=_normalize_optional_bool(item.get("allow_retrieval")),
            allow_llm_context=_normalize_optional_bool(item.get("allow_llm_context")),
            metadata=sanitize_metadata(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
        )


@dataclass(frozen=True, slots=True)
class MemorySearchIntent:
    """Normalized memory-search intent derived from runtime context."""

    query: str
    scope: MemoryScope
    limit: int
    include_document_chunks: bool
    include_agent_memories: bool
    max_result_chars: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", _normalize_text(self.query))
        if self.limit <= 0:
            raise ValueError("Memory search limit must be positive.")
        if self.max_result_chars <= 0:
            raise ValueError("Memory max_result_chars must be positive.")
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


def build_memory_search_intent(
    context: OrchestrationContext,
    *,
    agent_name: str,
    max_result_chars: int = 400,
) -> MemorySearchIntent:
    usecase_settings = _resolve_usecase_settings(context)
    default_limit = 5 if context.strategy_settings is None else context.strategy_settings.memory.default_limit
    include_document_chunks = _include_document_chunks(context)
    include_agent_memories = _include_agent_memories(context)
    return MemorySearchIntent(
        query=context.request.message,
        scope=build_memory_scope(context, agent_name=agent_name),
        limit=max(1, default_limit),
        include_document_chunks=include_document_chunks,
        include_agent_memories=include_agent_memories,
        max_result_chars=max_result_chars,
        metadata={
            "usecase": context.request.usecase,
            "usecase_memory_enabled": None if usecase_settings is None else usecase_settings.memory.enabled,
        },
    )


def build_memory_scope(
    context: OrchestrationContext,
    *,
    agent_name: str,
) -> MemoryScope:
    _ = agent_name
    runtime = context.runtime
    return MemoryScope(
        project_id=None if runtime is None else runtime.project_id,
        tenant_id=None if runtime is None else runtime.tenant_id,
    )


def build_memory_candidates(
    context: OrchestrationContext,
    *,
    candidate_limit: int,
) -> list[MemoryCandidate]:
    if candidate_limit <= 0:
        raise ValueError("Memory candidate limit must be positive.")

    explicit = _read_explicit_memory_candidates(context)
    if explicit:
        return explicit[:candidate_limit]

    inferred = _infer_memory_candidate(context.request.message, context=context)
    return inferred[:candidate_limit]


def build_memory_candidate_scope(
    context: OrchestrationContext,
    *,
    candidate: MemoryCandidate,
    agent_name: str | None,
) -> MemoryScope:
    runtime = context.runtime
    scope_name = _normalize_candidate_scope(candidate.scope)
    user_id = context.request.user_id
    project_id = None if runtime is None else runtime.project_id
    tenant_id = None if runtime is None else runtime.tenant_id
    session_id = context.request.session_id
    usecase = context.request.usecase
    resolved_agent = _normalize_optional_text(agent_name)

    if scope_name == "project_user":
        scope = MemoryScope(
            user_id=user_id,
            project_id=project_id,
            tenant_id=tenant_id,
        )
    elif scope_name == "project":
        scope = MemoryScope(project_id=project_id, tenant_id=tenant_id)
    elif scope_name == "user":
        scope = MemoryScope(user_id=user_id, tenant_id=tenant_id)
    elif scope_name == "tenant":
        scope = MemoryScope(tenant_id=tenant_id)
    elif scope_name == "session":
        scope = MemoryScope(
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
            tenant_id=tenant_id,
        )
    elif scope_name == "agent":
        scope = MemoryScope(
            agent_name=resolved_agent,
            user_id=user_id,
            project_id=project_id,
            tenant_id=tenant_id,
        )
    else:
        scope = MemoryScope(
            usecase=usecase,
            user_id=user_id,
            project_id=project_id,
            tenant_id=tenant_id,
        )

    if scope.has_durable_scope():
        return scope
    if user_id is not None:
        return MemoryScope(
            user_id=user_id,
            project_id=scope.project_id,
            tenant_id=scope.tenant_id,
            session_id=scope.session_id,
            agent_name=scope.agent_name,
            usecase=scope.usecase,
            source_id=scope.source_id,
            document_id=scope.document_id,
            tags=scope.tags,
            metadata=scope.metadata,
        )
    if project_id is not None:
        return MemoryScope(
            user_id=scope.user_id,
            project_id=project_id,
            tenant_id=scope.tenant_id,
            session_id=scope.session_id,
            agent_name=scope.agent_name,
            usecase=scope.usecase,
            source_id=scope.source_id,
            document_id=scope.document_id,
            tags=scope.tags,
            metadata=scope.metadata,
        )
    if tenant_id is not None:
        return MemoryScope(
            user_id=scope.user_id,
            project_id=scope.project_id,
            tenant_id=tenant_id,
            session_id=scope.session_id,
            agent_name=scope.agent_name,
            usecase=scope.usecase,
            source_id=scope.source_id,
            document_id=scope.document_id,
            tags=scope.tags,
            metadata=scope.metadata,
        )
    return scope


def build_memory_search_request(intent: MemorySearchIntent) -> MemorySearchRequest:
    return MemorySearchRequest(
        text=intent.query,
        scope=intent.scope,
        limit=intent.limit,
        include_document_chunks=intent.include_document_chunks,
        include_agent_memories=intent.include_agent_memories,
        max_result_chars=intent.max_result_chars,
        metadata=dict(intent.metadata),
    )


def build_memory_context_block(
    search_result: MemorySearchResult,
    *,
    max_items: int = 8,
    max_bytes: int = 3200,
    max_item_chars: int = 400,
) -> BudgetedContext:
    items: list[ContextBudgetItem] = []
    for index, result in enumerate(search_result.results[:max_items], start=1):
        excerpt = memory_result_excerpt(result, max_chars=max_item_chars)
        if excerpt is None:
            continue
        items.append(ContextBudgetItem(text=excerpt, label=f"[{index}]"))

    return budget_context_items(
        items,
        budget=ContextBudget(max_bytes=max_bytes, max_items=max_items),
        prefix="Retrieved context:",
        empty_text="No retrieved context.",
    )


def build_memory_prompt_section(
    search_result: MemorySearchResult,
    *,
    max_items: int = 8,
    max_bytes: int = 3200,
    max_item_chars: int = 400,
) -> PromptSection:
    bounded = build_memory_context_block(
        search_result,
        max_items=max_items,
        max_bytes=max_bytes,
        max_item_chars=max_item_chars,
    )
    return PromptSection(title="Retrieved context", body=bounded.text.removeprefix("Retrieved context:\n"))


def build_memory_search_summary(
    search_result: MemorySearchResult,
    *,
    source: str = "memory",
    context_item_count: int,
) -> MemorySearchSummary:
    return MemorySearchSummary(
        source=source,
        result_count=len(search_result.results),
        metadata={
            "context_item_count": context_item_count,
            "query_id": search_result.query_id,
        },
    )


def memory_result_excerpt(item: MemoryResult, *, max_chars: int = 400) -> str | None:
    title = None
    if isinstance(item.record, MemoryRecord) and item.record.title:
        title = item.record.title
    elif item.source_id:
        title = item.source_id

    text = item.text.strip()
    if not text:
        return None
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    if title:
        return f"{title}: {text}"
    return text


def _include_document_chunks(context: OrchestrationContext) -> bool:
    if context.strategy_settings is None or not context.strategy_settings.memory_enabled:
        return False
    usecase = _resolve_usecase_settings(context)
    if usecase is None:
        return True
    return bool(usecase.memory.include_document_chunks)


def _include_agent_memories(context: OrchestrationContext) -> bool:
    if context.strategy_settings is None:
        return True
    return bool(context.strategy_settings.memory.include_user_memory)


def _resolve_usecase_settings(context: OrchestrationContext) -> Any | None:
    if context.settings is None or context.request.usecase is None:
        return None
    return context.settings.usecases.get(context.request.usecase)


def _read_explicit_memory_candidates(context: OrchestrationContext) -> list[MemoryCandidate]:
    raw_candidates = context.request.metadata.get("memory_candidates")
    if not isinstance(raw_candidates, list):
        return []

    candidates: list[MemoryCandidate] = []
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        try:
            candidates.append(MemoryCandidate.from_mapping(item))
        except (TypeError, ValueError):
            continue
    return candidates


def _infer_memory_candidate(
    message: str,
    *,
    context: OrchestrationContext,
) -> list[MemoryCandidate]:
    lowered = message.casefold()
    for pattern in _EXPLICIT_MEMORY_PATTERNS:
        match = pattern.match(message)
        if match is None:
            continue
        extracted = _normalize_optional_text(match.group("text"))
        if extracted is None:
            return []
        return [
            MemoryCandidate(
                text=extracted,
                memory_type="preference" if "prefer" in lowered or "preference" in lowered else "user_fact",
                scope="project_user" if context.runtime is not None and context.runtime.project_id is not None else "user",
                reason="explicit_remember_request",
                metadata={"source": "request_message"},
            )
        ]
    return []


def _normalize_text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("Memory intent text must be a string.")
    normalized = value.strip()
    if not normalized:
        raise ValueError("Memory intent text must not be empty.")
    return normalized


def _normalize_candidate_scope(value: object) -> MemoryCandidateScope:
    if not isinstance(value, str):
        return "project_user"
    normalized = value.strip().casefold().replace("-", "_")
    if normalized not in _ALLOWED_MEMORY_CANDIDATE_SCOPES:
        return "project_user"
    return normalized  # type: ignore[return-value]


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _normalize_optional_positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None


def _normalize_optional_bool(value: object) -> bool | None:
    if not isinstance(value, bool):
        return None
    return value


def _normalize_tags(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    tags: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        if normalized:
            tags.append(normalized)
    return tuple(tags)