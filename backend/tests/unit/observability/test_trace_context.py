import asyncio

from app.observability.context import (
    TraceContext,
    bind_trace_context,
    get_trace_context,
    get_trace_id,
    reset_trace_context,
    set_trace_context,
)


async def _current_trace_id_after_yield() -> str | None:
    await asyncio.sleep(0)
    return get_trace_id()


async def test_trace_context_flows_across_async_boundaries() -> None:
    trace_id = "trace_0123456789abcdef0123456789abcdef"
    token = set_trace_context(TraceContext(trace_id=trace_id))

    try:
        assert await _current_trace_id_after_yield() == trace_id
        assert await asyncio.create_task(_current_trace_id_after_yield()) == trace_id
    finally:
        reset_trace_context(token)


async def test_reset_trace_context_restores_previous_state() -> None:
    outer_token = set_trace_context(TraceContext(trace_id="trace_outer_12345678"))

    try:
        inner_token = set_trace_context(TraceContext(trace_id="trace_inner_12345678"))
        try:
            assert get_trace_id() == "trace_inner_12345678"
        finally:
            reset_trace_context(inner_token)

        assert get_trace_id() == "trace_outer_12345678"
    finally:
        reset_trace_context(outer_token)

    assert get_trace_context() is None


async def test_trace_context_is_cleared_after_reset() -> None:
    token = bind_trace_context(trace_id="trace_reset_12345678")
    reset_trace_context(token)

    assert get_trace_context() is None
    assert await asyncio.create_task(_current_trace_id_after_yield()) is None