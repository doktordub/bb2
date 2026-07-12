from __future__ import annotations

import json
from pathlib import Path


OPENAPI_PATH = Path(__file__).resolve().parents[1] / "openAPI.json"


def load_spec() -> dict[str, object]:
    return json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))


def get_schema(spec: dict[str, object], name: str) -> dict[str, object]:
    schemas = spec["components"]["schemas"]
    return schemas[name]


def resolve_schema(spec: dict[str, object], schema: dict[str, object]) -> dict[str, object]:
    reference = schema.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/components/schemas/"):
        return get_schema(spec, reference.rsplit("/", 1)[-1])
    return schema


def assert_nullable_string_field(schema: dict[str, object], field_name: str) -> None:
    field = schema["properties"][field_name]
    options = field.get("anyOf", [])
    assert {option.get("type") for option in options} == {"string", "null"}


def test_checked_in_openapi_snapshot_exists() -> None:
    assert OPENAPI_PATH.is_file()


def test_required_frontend_paths_exist() -> None:
    spec = load_spec()
    paths = set(spec["paths"].keys())

    assert {
        "/health",
        "/capabilities",
        "/chat",
        "/chat/stream",
        "/sessions",
        "/sessions/{session_id}/history",
        "/sessions/{session_id}/reset",
        "/sessions/{session_id}",
        "/debug/traces",
        "/debug/traces/{trace_id}",
        "/restart",
    }.issubset(paths)


def test_chat_request_contract_matches_frontend_expectations() -> None:
    spec = load_spec()
    chat_request = get_schema(spec, "ChatRequest")

    assert chat_request["required"] == ["message"]
    assert "message" in chat_request["properties"]
    assert_nullable_string_field(chat_request, "session_id")
    assert_nullable_string_field(chat_request, "usecase")


def test_chat_response_contract_matches_frontend_expectations() -> None:
    spec = load_spec()
    chat_response = get_schema(spec, "ChatResponse")
    chat_response_data = resolve_schema(spec, chat_response["properties"]["data"])

    assert {"trace_id", "session_id", "data"}.issubset(set(chat_response["required"]))
    assert "answer" in chat_response_data["properties"]


def test_capabilities_contract_matches_frontend_expectations() -> None:
    spec = load_spec()
    capabilities_response = get_schema(spec, "CapabilitiesResponse")
    capabilities_data = resolve_schema(spec, capabilities_response["properties"]["data"])
    chat_capabilities = resolve_schema(spec, capabilities_data["properties"]["chat"])
    session_capabilities = resolve_schema(spec, capabilities_data["properties"]["sessions"])
    visualization_capabilities = resolve_schema(spec, capabilities_data["properties"]["visualization"])

    assert "data" in capabilities_response["required"]
    assert {"enabled", "streaming_enabled", "max_message_chars"}.issubset(
        set(chat_capabilities["properties"].keys())
    )
    assert {"list_enabled", "history_enabled", "reset_enabled", "delete_enabled"}.issubset(
        set(session_capabilities["properties"].keys())
    )
    assert {
        "enabled",
        "default_renderer",
        "spec_version",
        "supported_chart_types",
        "reference_mode_enabled",
        "limits",
    }.issubset(set(visualization_capabilities["properties"].keys()))


def test_session_contract_matches_frontend_expectations() -> None:
    spec = load_spec()
    session_summary = get_schema(spec, "SessionSummaryData")
    history_message = get_schema(spec, "SessionHistoryMessageData")

    assert {
        "session_id",
        "usecase",
        "status",
        "created_at",
        "updated_at",
        "last_activity_at",
        "reset_count",
        "message_count",
    }.issubset(set(session_summary["properties"].keys()))
    assert {"role", "content", "artifacts", "metadata"}.issubset(
        set(history_message["properties"].keys())
    )