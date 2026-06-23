from app.contracts.context import OrchestrationContext, RequestContext


def test_request_context_defaults() -> None:
    request = RequestContext(
        user_id="user_1",
        session_id="session_1",
        message="hello",
    )

    assert request.usecase is None
    assert request.trace_id is None
    assert request.metadata == {}


def test_request_context_metadata_is_not_shared() -> None:
    first = RequestContext(
        user_id="user_1",
        session_id="session_1",
        message="hello",
    )
    second = RequestContext(
        user_id="user_2",
        session_id="session_2",
        message="hi",
    )

    first.metadata["tenant_id"] = "tenant_1"

    assert second.metadata == {}


def test_orchestration_context_keeps_request_and_capabilities() -> None:
    request = RequestContext(
        user_id="user_1",
        session_id="session_1",
        message="hello",
        trace_id="trace_1",
    )
    llm = object()
    memory = object()
    state = object()
    tools = object()
    trace = object()
    policy = object()
    config = object()

    context = OrchestrationContext(
        request=request,
        llm=llm,
        memory=memory,
        state=state,
        tools=tools,
        trace=trace,
        policy=policy,
        config=config,
        runtime_metadata={"strategy": "direct"},
    )

    assert context.request is request
    assert context.llm is llm
    assert context.memory is memory
    assert context.state is state
    assert context.tools is tools
    assert context.trace is trace
    assert context.policy is policy
    assert context.config is config
    assert context.runtime_metadata == {"strategy": "direct"}