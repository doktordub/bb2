"""Compatibility shim for the phase-3 memory runtime relocation."""

from app.memory.adapters.memory_store import (
    MemoryStoreAdapter,
    _load_memory_store_runtime,
    normalize_memory_search_limit,
)

__all__ = [
    "MemoryStoreAdapter",
    "_load_memory_store_runtime",
    "normalize_memory_search_limit",
]