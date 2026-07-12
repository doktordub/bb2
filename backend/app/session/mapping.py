"""Mapping helpers between API/session/core request and result models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from app.config.view import get_visualization_settings
from app.contracts.config import ConfigurationView
from app.contracts.context import RequestContext
from app.contracts.state import WorkflowStateDocument
from app.orchestration.context import build_orchestration_request, build_runtime_context
from app.orchestration.models import (
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationRuntimeContext,
    sanitize_metadata,
)
from app.orchestration.state_delta import WorkflowStateSnapshot
from app.persistence.serialization import dumps_json
from app.session.models import SessionChatRequest, SessionChatResult, SessionRequestContext
from app.visualization.settings import VisualizationHistoryReplaySettings


@dataclass(frozen=True, slots=True)
class HistoryReplayPayload:
    """Bounded replay payload persisted with assistant history messages."""

    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def build_session_chat_request(
    *,
    message: str,
    session_id: str | None,
    usecase: str | None,
    metadata: Mapping[str, Any] | None = None,
) -> SessionChatRequest:
    """Build a session-owned request DTO from validated upstream values."""

    return SessionChatRequest(
        message=message,
        session_id=session_id,
        usecase=usecase,
        metadata=dict(metadata or {}),
    )


def build_session_request_context(
    *,
    trace_id: str,
    request_id: str,
    user_id: str,
    user_id_hash: str | None,
    client_host: str | None,
    user_agent: str | None,
    path: str | None,
    method: str | None,
    metadata: Mapping[str, Any] | None = None,
    headers_safe: Mapping[str, str] | None = None,
) -> SessionRequestContext:
    """Build a session-owned request context from safe upstream metadata."""

    resolved_metadata = dict(metadata or {})
    if headers_safe:
        resolved_metadata["headers_safe"] = dict(headers_safe)

    return SessionRequestContext(
        trace_id=trace_id,
        request_id=request_id,
        user_id=user_id,
        user_id_hash=user_id_hash,
        client_host=client_host,
        user_agent=user_agent,
        path=path,
        method=method,
        metadata=resolved_metadata,
    )


def build_core_request_context(
    *,
    request: SessionChatRequest,
    context: SessionRequestContext,
    session_id: str,
    default_usecase: str | None = None,
) -> RequestContext:
    """Map a session request into the orchestration-facing request contract."""

    metadata: dict[str, Any] = {
        **dict(context.metadata),
        **dict(request.metadata),
        "trace_id": context.trace_id,
        "request_id": context.request_id,
    }
    if context.path is not None:
        metadata["path"] = context.path
    if context.method is not None:
        metadata["method"] = context.method
    if context.user_id_hash is not None:
        metadata["user_id_hash"] = context.user_id_hash
    if context.client_host is not None:
        metadata["client_host"] = context.client_host
    if context.user_agent is not None:
        metadata["user_agent"] = context.user_agent

    return RequestContext(
        user_id=context.user_id,
        session_id=session_id,
        message=request.message,
        usecase=request.usecase or default_usecase,
        trace_id=context.trace_id,
        metadata=metadata,
    )


def build_session_orchestration_request(
    *,
    request_context: RequestContext,
    state: WorkflowStateSnapshot | WorkflowStateDocument | None = None,
    version: int | None = None,
) -> OrchestrationRequest:
    """Build the orchestration-owned request DTO for one session turn."""

    return build_orchestration_request(
        request=request_context,
        state=state,
        version=version,
    )


def build_session_orchestration_context(
    *,
    request_context: RequestContext,
    metadata: Mapping[str, Any] | None = None,
) -> OrchestrationRuntimeContext:
    """Build the orchestration runtime context for one session turn."""

    return build_runtime_context(request_context, metadata=metadata)


def orchestration_result_to_session_result(
    result: OrchestrationResult,
    *,
    trace_id: str,
) -> SessionChatResult:
    """Map the canonical orchestration result into the session boundary model."""

    artifacts = [item.model_dump(mode="python") for item in result.artifacts]
    context_contributions = [
        item.model_dump(mode="python") for item in result.context_contributions
    ]
    return SessionChatResult(
        answer=result.answer,
        session_id=result.session_id,
        trace_id=result.trace_id or trace_id,
        agent_name=result.agent_name,
        strategy_name=result.strategy_name,
        llm_profile=result.llm_profile,
        tool_calls=[item.as_legacy_dict() for item in result.tool_calls],
        memory_updates=[item.as_legacy_dict() for item in result.memory_updates],
        artifacts=artifacts,
        metadata=merge_session_result_metadata(
            base_metadata=result.metadata,
            artifacts=artifacts,
            context_contributions=context_contributions,
        ),
    )


def merge_session_result_metadata(
    *,
    base_metadata: Mapping[str, Any] | None,
    artifacts: list[dict[str, Any]],
    context_contributions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge orchestration metadata with additive visualization metadata."""

    metadata = sanitize_metadata(base_metadata)
    visualization_metadata = build_visualization_response_metadata(
        artifacts=artifacts,
        context_contributions=context_contributions,
    )
    metadata.update(visualization_metadata)
    metadata.setdefault("generated_artifact_count", len(artifacts))
    if "pending_task_count" not in metadata:
        pending_task_count = _resolve_pending_task_count(metadata)
        if pending_task_count is not None:
            metadata["pending_task_count"] = pending_task_count
    return metadata


def build_visualization_response_metadata(
    *,
    artifacts: list[dict[str, Any]],
    context_contributions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build frontend-safe visualization metadata for public chat responses."""

    metadata: dict[str, Any] = {}
    artifact_count = len(artifacts)
    if artifact_count:
        metadata["artifact_count"] = artifact_count
        metadata["artifact_delivery_mode"] = _artifact_delivery_mode(artifacts)

    context_summary_ids = _context_summary_ids(context_contributions)
    if artifact_count or context_summary_ids:
        metadata["context_summary_added"] = bool(context_summary_ids)
    if context_summary_ids:
        metadata["context_summary_ids"] = context_summary_ids
        if len(context_summary_ids) == 1:
            metadata["context_summary_id"] = context_summary_ids[0]
    return metadata


def resolve_public_artifact_retrieval_endpoint(
    config: ConfigurationView,
) -> str | None:
    """Return the client-facing artifact retrieval path template when enabled."""

    try:
        settings = get_visualization_settings(config)
    except Exception:
        return None

    if not settings.enabled or not settings.artifact_store.public_retrieval_enabled:
        return None

    return _read_optional_text(settings.artifact_store.retrieval_endpoint)


def project_public_artifact(
    artifact: Mapping[str, Any],
    *,
    artifact_retrieval_endpoint: str | None,
    force_reference: bool = False,
) -> dict[str, Any] | None:
    """Rewrite one visualization artifact for the browser-facing contract."""

    payload = dict(artifact)
    artifact_id = _read_optional_text(payload.get("artifact_id"))
    if artifact_id is None:
        return None if force_reference else payload

    if force_reference:
        public_data_ref = _build_public_artifact_data_ref(
            artifact_id=artifact_id,
            artifact_retrieval_endpoint=artifact_retrieval_endpoint,
        )
        if public_data_ref is None:
            return None
        payload["data_mode"] = "reference"
        payload["data"] = None
        payload["data_ref"] = public_data_ref
        return payload

    if _read_optional_text(payload.get("data_mode")) == "reference":
        public_data_ref = _build_public_artifact_data_ref(
            artifact_id=artifact_id,
            artifact_retrieval_endpoint=artifact_retrieval_endpoint,
        )
        if public_data_ref is not None:
            payload["data_ref"] = public_data_ref

    return payload


def project_public_artifacts(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    artifact_retrieval_endpoint: str | None,
) -> list[dict[str, Any]]:
    """Rewrite a collection of browser-facing artifacts using public retrieval paths."""

    projected: list[dict[str, Any]] = []
    for artifact in artifacts:
        projected_artifact = project_public_artifact(
            artifact,
            artifact_retrieval_endpoint=artifact_retrieval_endpoint,
        )
        if projected_artifact is not None:
            projected.append(projected_artifact)
    return projected


def build_history_replay_payload(
    *,
    artifacts: Sequence[Mapping[str, Any]],
    artifact_retrieval_endpoint: str | None,
    history_replay_settings: VisualizationHistoryReplaySettings | None = None,
) -> HistoryReplayPayload:
    """Build bounded assistant-message replay artifacts and compatibility metadata."""

    resolved_settings = history_replay_settings or VisualizationHistoryReplaySettings()

    safe_artifacts = [dict(item) for item in artifacts if isinstance(item, Mapping)]
    if not safe_artifacts:
        return HistoryReplayPayload()

    metadata: dict[str, Any] = {
        "artifact_count": len(safe_artifacts),
        "artifact_delivery_mode": _artifact_delivery_mode(safe_artifacts),
    }

    if not resolved_settings.enabled:
        metadata["artifact_replay_status"] = "disabled"
        metadata["artifact_replay_reason"] = "history_replay_disabled"
        return HistoryReplayPayload(metadata=metadata)

    replay_artifacts: list[dict[str, Any]] = []
    used_bytes = 0
    replay_reason: str | None = None

    for artifact in safe_artifacts[: resolved_settings.max_artifacts_per_message]:
        replay_artifact, artifact_bytes, artifact_reason = _select_history_replay_artifact(
            artifact,
            artifact_retrieval_endpoint=artifact_retrieval_endpoint,
            history_replay_settings=resolved_settings,
            used_bytes=used_bytes,
        )
        if replay_artifact is None:
            replay_reason = replay_reason or artifact_reason
            continue
        replay_artifacts.append(replay_artifact)
        used_bytes += artifact_bytes

    if len(safe_artifacts) > resolved_settings.max_artifacts_per_message:
        replay_reason = replay_reason or "artifact_limit_exceeded"

    if replay_artifacts:
        metadata["visualizations"] = replay_artifacts

    if not replay_artifacts:
        metadata["artifact_replay_status"] = "unavailable"
        metadata["artifact_replay_reason"] = replay_reason or "history_replay_unavailable"
    else:
        expected_replay_count = min(
            len(safe_artifacts),
            resolved_settings.max_artifacts_per_message,
        )
        if len(replay_artifacts) < expected_replay_count or len(safe_artifacts) > expected_replay_count:
            metadata["artifact_replay_status"] = "partial"
            if replay_reason is not None:
                metadata["artifact_replay_reason"] = replay_reason
        else:
            metadata["artifact_replay_status"] = "available"

    return HistoryReplayPayload(artifacts=replay_artifacts, metadata=metadata)


def build_history_visualization_metadata(
    *,
    artifacts: Sequence[Mapping[str, Any]],
    artifact_retrieval_endpoint: str | None,
    history_replay_settings: VisualizationHistoryReplaySettings | None = None,
) -> dict[str, Any]:
    """Return the compatibility metadata slice for persisted history replay."""

    return build_history_replay_payload(
        artifacts=artifacts,
        artifact_retrieval_endpoint=artifact_retrieval_endpoint,
        history_replay_settings=history_replay_settings,
    ).metadata


def _select_history_replay_artifact(
    artifact: Mapping[str, Any],
    *,
    artifact_retrieval_endpoint: str | None,
    history_replay_settings: VisualizationHistoryReplaySettings,
    used_bytes: int,
) -> tuple[dict[str, Any] | None, int, str | None]:
    inline_candidate = _build_history_inline_artifact_candidate(
        artifact,
        artifact_retrieval_endpoint=artifact_retrieval_endpoint,
    )
    reference_candidate = _build_history_reference_artifact_candidate(
        artifact,
        artifact_retrieval_endpoint=artifact_retrieval_endpoint,
    )

    candidates: list[tuple[str, dict[str, Any]]] = []
    if inline_candidate is not None and (
        history_replay_settings.prefer_inline or reference_candidate is None
    ):
        candidates.append(("inline", inline_candidate))
    if reference_candidate is not None:
        candidates.append(("reference", reference_candidate))
    if inline_candidate is not None and not history_replay_settings.prefer_inline and reference_candidate is not None:
        candidates.append(("inline", inline_candidate))

    if not candidates:
        data_mode = _read_optional_text(artifact.get("data_mode"))
        if data_mode == "reference":
            return None, 0, "reference_replay_unavailable"
        return None, 0, "inline_replay_unavailable"

    rejection_reason = "history_replay_unavailable"
    for candidate_mode, candidate in candidates:
        candidate_bytes = _serialized_json_bytes(candidate)
        if (
            candidate_mode == "inline"
            and candidate_bytes > history_replay_settings.max_inline_artifact_bytes
        ):
            rejection_reason = "inline_artifact_too_large"
            continue
        if used_bytes + candidate_bytes > history_replay_settings.max_total_bytes_per_message:
            rejection_reason = "message_replay_budget_exceeded"
            continue
        return candidate, candidate_bytes, None

    return None, 0, rejection_reason


def _build_history_inline_artifact_candidate(
    artifact: Mapping[str, Any],
    *,
    artifact_retrieval_endpoint: str | None,
) -> dict[str, Any] | None:
    candidate = project_public_artifact(
        artifact,
        artifact_retrieval_endpoint=artifact_retrieval_endpoint,
    )
    if candidate is None:
        return None
    if _read_optional_text(candidate.get("data_mode")) != "inline":
        return None
    if not isinstance(candidate.get("data"), list):
        return None
    return candidate


def _build_history_reference_artifact_candidate(
    artifact: Mapping[str, Any],
    *,
    artifact_retrieval_endpoint: str | None,
) -> dict[str, Any] | None:
    if _read_optional_text(artifact_retrieval_endpoint) is None:
        return None
    return project_public_artifact(
        artifact,
        artifact_retrieval_endpoint=artifact_retrieval_endpoint,
        force_reference=True,
    )


def _serialized_json_bytes(value: Mapping[str, Any]) -> int:
    return len(dumps_json(value).encode("utf-8"))


def _artifact_delivery_mode(artifacts: list[dict[str, Any]]) -> str:
    modes = {
        _read_optional_text(item.get("data_mode"))
        for item in artifacts
        if isinstance(item, Mapping)
    }
    normalized_modes = {mode for mode in modes if mode is not None}
    if not normalized_modes:
        return "inline"
    if len(normalized_modes) == 1:
        return next(iter(normalized_modes))
    return "mixed"


def _context_summary_ids(context_contributions: list[dict[str, Any]]) -> list[str]:
    summary_ids: list[str] = []
    seen: set[str] = set()
    for item in context_contributions:
        artifact_id = _read_optional_text(item.get("source_artifact_id"))
        if artifact_id is None:
            content = item.get("content")
            if isinstance(content, Mapping):
                artifact_id = _read_optional_text(content.get("artifact_id"))
        if artifact_id is None or artifact_id in seen:
            continue
        seen.add(artifact_id)
        summary_ids.append(artifact_id)
    return summary_ids


def _read_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def _resolve_pending_task_count(metadata: Mapping[str, Any]) -> int | None:
    plan_step_count = _optional_non_negative_int(metadata.get("plan_step_count"))
    if plan_step_count is None:
        return None
    executed_step_count = _optional_non_negative_int(metadata.get("executed_step_count")) or 0
    return max(plan_step_count - executed_step_count, 0)


def _build_public_artifact_data_ref(
    *,
    artifact_id: str,
    artifact_retrieval_endpoint: str | None,
) -> str | None:
    endpoint = _read_optional_text(artifact_retrieval_endpoint)
    if endpoint is None:
        return None

    encoded_artifact_id = quote(artifact_id, safe="")
    if "{artifact_id}" in endpoint:
        return endpoint.replace("{artifact_id}", encoded_artifact_id)

    normalized_endpoint = endpoint.rstrip("/")
    if not normalized_endpoint:
        return f"/artifacts/{encoded_artifact_id}"
    return f"{normalized_endpoint}/{encoded_artifact_id}"