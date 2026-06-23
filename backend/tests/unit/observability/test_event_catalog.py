from app.contracts import trace as trace_contract
from app.observability import events


def _runtime_event_constants() -> dict[str, str]:
    return {
        name: value
        for name, value in vars(events).items()
        if name.isupper() and isinstance(value, str)
    }


def _contract_event_constants() -> dict[str, str]:
    return {
        name: value
        for name, value in vars(trace_contract).items()
        if name.isupper() and isinstance(value, str)
    }


def test_runtime_event_catalog_has_unique_values() -> None:
    runtime_events = _runtime_event_constants()

    assert len(runtime_events) == len(set(runtime_events.values()))
    assert set(events.ALL_TRACE_EVENT_TYPES) == set(runtime_events.values())


def test_contract_trace_constants_remain_aligned_with_runtime_catalog() -> None:
    runtime_events = _runtime_event_constants()

    assert trace_contract.MINIMUM_TRACE_EVENT_TYPES == events.MINIMUM_TRACE_EVENT_TYPES
    for name, value in _contract_event_constants().items():
        assert runtime_events[name] == value