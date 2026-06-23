from app.observability.metrics import InMemoryMetricsRecorder, NoopMetricsRecorder


def test_in_memory_metrics_recorder_accepts_low_cardinality_tags() -> None:
    recorder = InMemoryMetricsRecorder()
    recorder.increment(
        "backend.requests.total",
        tags={
            "route": "/health",
            "method": "GET",
            "status_code": "200",
            "trace_id": "trace-secret",
        },
    )
    recorder.timing(
        "backend.requests.duration_ms",
        34,
        tags={
            "component": "api.health",
            "success": "true",
            "prompt_text": "should-not-appear",
        },
    )

    snapshot = recorder.snapshot()

    assert snapshot["counters"][0].tags == {
        "route": "/health",
        "method": "GET",
        "status_code": "200",
    }
    assert snapshot["timings"][0].tags == {
        "component": "api.health",
        "success": "true",
    }


def test_metrics_recorders_do_not_require_sensitive_tags() -> None:
    recorder = InMemoryMetricsRecorder()
    recorder.increment("backend.trace.events.total")
    recorder.timing("backend.trace.events.duration_ms", 12)

    snapshot = recorder.snapshot()

    assert snapshot["counters"][0].tags == {}
    assert snapshot["timings"][0].tags == {}

    noop = NoopMetricsRecorder()
    noop.increment("backend.requests.total", tags={"trace_id": "ignored"})
    noop.timing("backend.requests.duration_ms", 10, tags={"session_id": "ignored"})