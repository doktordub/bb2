from __future__ import annotations

from app.observability.metrics import InMemoryMetricsRecorder


def test_metrics_recorder_stores_only_low_cardinality_tags() -> None:
    recorder = InMemoryMetricsRecorder()

    recorder.increment(
        "mcp.tool.call.count",
        {
            "tool_name": "websearch.search",
            "status": "ok",
            "query": "should-not-be-tagged",
        },
    )
    recorder.timing(
        "mcp.tool.duration_ms",
        12.5,
        {
            "tool_name": "websearch.search",
            "status": "ok",
            "url": "https://example.com",
        },
    )

    assert recorder.counter_value(
        "mcp.tool.call.count",
        {"tool_name": "websearch.search", "status": "ok"},
    ) == 1
    assert recorder.timing_samples[0].tags == {
        "tool_name": "websearch.search",
        "status": "ok",
    }