# Backend Sample

## Memory

MemoryGateway is the orchestration-facing boundary for long-term memory and document chunk access.

## LLM Boundary

The LLM gateway must not search or write memory.

## API Boundary

API routes must delegate through SessionService and OrchestrationRuntime instead of calling memory directly.