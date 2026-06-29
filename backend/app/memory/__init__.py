"""Runtime ownership for backend long-term memory services."""

from app.memory.adapters import FakeMemoryAdapter, MemoryAdapter, MemoryStoreAdapter
from app.memory.context_builder import (
    MemoryContextBuilder,
    build_memory_context,
    build_memory_prompt_context,
)
from app.memory.errors import MemoryConfigurationError
from app.memory.factory import build_memory_gateway
from app.memory.gateway import DefaultMemoryGateway, UnavailableMemoryGateway
from app.memory.scopes import classify_memory_scope, normalize_memory_scope, scope_summary

__all__ = [
    "DefaultMemoryGateway",
    "FakeMemoryAdapter",
    "MemoryAdapter",
    "MemoryContextBuilder",
    "MemoryConfigurationError",
    "MemoryStoreAdapter",
    "UnavailableMemoryGateway",
    "build_memory_context",
    "build_memory_prompt_context",
    "build_memory_gateway",
    "classify_memory_scope",
    "normalize_memory_scope",
    "scope_summary",
]