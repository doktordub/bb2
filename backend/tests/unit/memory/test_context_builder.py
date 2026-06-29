from __future__ import annotations

from app.contracts.memory import (
    MemoryChunkContextResult,
    MemoryPromptContext,
    MemoryRecord,
    MemoryResult,
    MemoryScope,
    MemorySource,
)
from app.memory.context_builder import (
    MemoryContextBuilder,
    build_memory_context,
    build_memory_prompt_context,
)


def test_memory_context_builder_builds_bounded_prompt_context_with_chunk_windows() -> None:
    document_scope = MemoryScope(project_id="project-1")
    before_record = MemoryRecord(
        memory_id="memory-1",
        text="Before context paragraph.",
        memory_type="document_chunk",
        scope=document_scope,
        title="Guide",
        source=MemorySource(
            source_id="source-1",
            document_id="doc-1",
            chunk_id="chunk-1",
            chunk_index=1,
            section_path=("Guide", "Memory Boundary"),
        ),
    )
    target_record = MemoryRecord(
        memory_id="memory-2",
        text="The LLM gateway must not search or write memory. Memory access is through MemoryGateway.",
        memory_type="document_chunk",
        scope=document_scope,
        title="Guide",
        source=MemorySource(
            source_id="source-1",
            document_id="doc-1",
            chunk_id="chunk-2",
            chunk_index=2,
            section_path=("Guide", "Memory Boundary"),
        ),
    )
    after_record = MemoryRecord(
        memory_id="memory-3",
        text="After context paragraph.",
        memory_type="document_chunk",
        scope=document_scope,
        title="Guide",
        source=MemorySource(
            source_id="source-1",
            document_id="doc-1",
            chunk_id="chunk-3",
            chunk_index=3,
            section_path=("Guide", "Memory Boundary"),
        ),
    )
    secondary_record = MemoryRecord(
        memory_id="memory-4",
        text="This secondary memory should be omitted once the context budget is exhausted.",
        memory_type="project_fact",
        scope=document_scope,
        title="Secondary",
        source=MemorySource(source_id="source-2", document_id="doc-2"),
    )

    results = [
        MemoryResult.from_record(target_record, score=0.92),
        MemoryResult.from_record(secondary_record, score=0.40),
    ]
    chunk_contexts = {
        "chunk-2": MemoryChunkContextResult(
            chunk=MemoryResult.from_record(target_record, score=0.92),
            before=[MemoryResult.from_record(before_record, score=0.10)],
            after=[MemoryResult.from_record(after_record, score=0.10)],
        )
    }

    context = MemoryContextBuilder(
        max_total_chars=205,
        max_result_chars=120,
        include_sources=True,
    ).build_context(search_result=results, chunk_contexts=chunk_contexts)

    assert isinstance(context, MemoryPromptContext)
    assert context.text.startswith("[1] Document chunk, source=Guide, section=\"Guide > Memory Boundary\"")
    assert "MemoryGateway" in context.text
    assert context.included_memory_ids == ("memory-1", "memory-2", "memory-3")
    assert context.omitted_memory_ids == ("memory-4",)
    assert context.total_chars <= 205
    assert context.truncated is True


def test_build_memory_context_keeps_text_only_compatibility() -> None:
    record = MemoryRecord(
        memory_id="memory-1",
        text="Compatibility body",
        memory_type="project_fact",
        scope=MemoryScope(project_id="project-1"),
        title="Compatibility",
        source=MemorySource(source_id="source-1"),
    )
    results = [MemoryResult.from_record(record, score=0.5)]

    prompt_context = build_memory_prompt_context(
        results,
        max_total_chars=120,
        max_result_chars=60,
    )
    text_context = build_memory_context(
        results,
        max_total_chars=120,
        max_result_chars=60,
    )

    assert prompt_context.text == text_context
    assert "Compatibility body" in text_context