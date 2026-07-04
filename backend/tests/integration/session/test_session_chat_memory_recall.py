from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config.settings import load_settings
from app.contracts.llm import LLMRequest, LLMResponse, LLMStreamEvent, LLMTokenUsage
from app.main import create_app
from app.testing.fakes import FakeLLMGateway


SETTINGS_ENV_VARS = [
    "APP_ENV",
    "APP_DEBUG",
    "APP_USECASE",
    "APP_CONFIG_PATH",
    "APP_CONFIG_OVERRIDE_PATH",
    "APP_DATA_DIR",
    "APP_CONFIG_STRICT",
    "BACKEND_HOST",
    "BACKEND_PORT",
    "BACKEND_RELOAD",
    "LOG_LEVEL",
    "LOG_JSON",
    "MCP_MAIN_URL",
    "LLM_LOCAL_QWEN_BASE_URL",
    "LLM_LOCAL_QWEN_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "MEMORY_STORE_CONFIG",
    "SQLITE_WORKFLOW_STATE_URL",
    "SQLITE_TRACE_URL",
]


class ContinuityProbeLLMGateway(FakeLLMGateway):
    def _resolve_response_text(self, request: LLMRequest) -> str:
        prompt_text = "\n".join(
            item.content if isinstance(item.content, str) else " ".join(part.text or "" for part in item.content)
            for item in request.messages
        )
        if "What is my name?" in prompt_text and "I am Bob" in prompt_text:
            return "Bob"
        if "What is my name?" in prompt_text:
            return "continuity-missing"
        return "acknowledged"

    async def complete(self, request: LLMRequest, context):  # type: ignore[override]
        self.requests.append(request)
        self.contexts.append(context)
        profile = request.profile or self.default_profile
        return LLMResponse(
            text=self._resolve_response_text(request),
            profile=profile,
            provider=self.provider_name,
            model=self.model_name,
            finish_reason="completed",
            usage=LLMTokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            metadata={"component": request.component} if request.component else {},
        )

    async def stream(self, request: LLMRequest, context):  # type: ignore[override]
        self.requests.append(request)
        self.contexts.append(context)
        profile = request.profile or self.default_profile
        response_text = self._resolve_response_text(request)
        metadata = {"component": request.component} if request.component else {}
        yield LLMStreamEvent.started(
            profile=profile,
            provider=self.provider_name,
            model=self.model_name,
            metadata=metadata,
        )
        yield LLMStreamEvent.delta(
            text=response_text,
            profile=profile,
            provider=self.provider_name,
            model=self.model_name,
        )
        yield LLMStreamEvent.completed(
            profile=profile,
            provider=self.provider_name,
            model=self.model_name,
            finish_reason="completed",
            usage=LLMTokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        )


def _build_app(monkeypatch: pytest.MonkeyPatch, tmp_path) -> object:
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("APP_CONFIG_PATH", "tests/fixtures/config/valid_minimal.yaml")
    monkeypatch.setenv(
        "APP_CONFIG_OVERRIDE_PATH",
        "tests/fixtures/config/session_prompt_history_enabled.yaml",
    )
    monkeypatch.setenv("APP_DATA_DIR", tmp_path.as_posix())
    return create_app(load_settings(env_file=None))


def _install_probe_gateway(app) -> None:
    probe = ContinuityProbeLLMGateway(default_profile="fake_streaming")
    object.__setattr__(app.state.container, "llm_gateway", probe)
    object.__setattr__(app.state.container.orchestrator, "llm_gateway", probe)


def test_chat_route_recalls_prior_turn_when_conversation_context_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = _build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        _install_probe_gateway(app)
        first = client.post(
            "/chat",
            headers={"x-trace-id": "trace-recall-0001"},
            json={"message": "I am Bob", "session_id": "session_recall_1"},
        )
        second = client.post(
            "/chat",
            headers={"x-trace-id": "trace-recall-0002"},
            json={"message": "What is my name?", "session_id": "session_recall_1"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["answer"] == "Bob"


def test_stream_route_recalls_prior_turn_when_conversation_context_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = _build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        _install_probe_gateway(app)
        warmup = client.post(
            "/chat",
            headers={"x-trace-id": "trace-stream-recall-0001"},
            json={"message": "I am Bob", "session_id": "session_stream_recall_1"},
        )
        response = client.post(
            "/chat/stream",
            headers={"x-trace-id": "trace-stream-recall-0002"},
            json={"message": "What is my name?", "session_id": "session_stream_recall_1"},
        )

    assert warmup.status_code == 200
    assert response.status_code == 200
    chunks = [chunk for chunk in response.text.strip().split("\n\n") if chunk]
    payloads = [
        json.loads(next(line for line in chunk.splitlines() if line.startswith("data: ")).removeprefix("data: "))
        for chunk in chunks
    ]
    deltas = [payload.get("text") for payload in payloads if payload.get("text")]
    assert deltas == ["Bob"]


def test_chat_route_recalls_prior_turn_from_session_summary_when_raw_history_compacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    app = _build_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        _install_probe_gateway(app)
        session_id = "session_recall_summary_1"
        seed_messages = [
            "I am Bob",
            "Filler turn 2",
            "Filler turn 3",
            "Filler turn 4",
            "Filler turn 5",
            "Filler turn 6",
            "Filler turn 7",
        ]
        for index, message in enumerate(seed_messages, start=1):
            response = client.post(
                "/chat",
                headers={"x-trace-id": f"trace-summary-{index:04d}"},
                json={"message": message, "session_id": session_id},
            )
            assert response.status_code == 200

        follow_up = client.post(
            "/chat",
            headers={"x-trace-id": "trace-summary-9999"},
            json={"message": "What is my name?", "session_id": session_id},
        )

    assert follow_up.status_code == 200
    assert follow_up.json()["data"]["answer"] == "Bob"