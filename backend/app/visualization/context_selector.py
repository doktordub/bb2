"""Selection and persistence helpers for prompt-safe visualization context."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from app.visualization.models import ChartContextSummary, ContextContribution
from app.visualization.settings import VisualizationSettings
from app.visualization.validators import estimate_chart_summary_tokens, validate_chart_context_summary

_SUMMARY_KEYS = ("summaries", "chart_summaries", "recent_charts")


def collect_chart_summaries(*containers: object) -> tuple[ChartContextSummary, ...]:
    """Collect deduplicated chart summaries from workflow-state or request metadata."""

    summaries: list[ChartContextSummary] = []
    seen: set[str] = set()
    for container in containers:
        visualization_context = _resolve_visualization_context(container)
        if visualization_context is None:
            continue
        for item in _iter_raw_summaries(visualization_context):
            summary = _coerce_chart_summary(item)
            if summary is None or summary.artifact_id in seen:
                continue
            summaries.append(summary)
            seen.add(summary.artifact_id)
    return tuple(summaries)


def merge_visualization_context(
    *,
    existing: Sequence[ChartContextSummary],
    contributions: Sequence[ContextContribution],
    active_usecase: str | None,
    settings: VisualizationSettings,
) -> dict[str, Any]:
    """Merge validated chart summaries into one bounded persisted context payload."""

    merged: list[ChartContextSummary] = list(existing)
    for contribution in contributions:
        summary = validate_chart_context_contribution(
            contribution=contribution,
            settings=settings,
        )
        if summary is None:
            continue
        merged.append(_with_usecase(summary, active_usecase=active_usecase))

    selected = _select_for_storage(
        summaries=_dedupe_latest(merged),
        active_usecase=active_usecase,
        settings=settings,
    )
    payload = [summary.model_dump(mode="python") for summary in selected]
    return {
        "summaries": payload,
        "summary_count": len(payload),
    }


def select_chart_summaries_for_prompt(
    *,
    message: str | None,
    summaries: Sequence[ChartContextSummary],
    active_usecase: str | None,
    settings: VisualizationSettings,
) -> tuple[ChartContextSummary, ...]:
    """Select the most relevant persisted chart summaries for the next prompt."""

    if not settings.enabled or not settings.context_summary.enabled or not summaries:
        return ()

    normalized_message = (message or "").casefold()
    scored: list[tuple[int, int, int, ChartContextSummary]] = []
    for index, summary in enumerate(summaries):
        scored.append(
            (
                _explicit_reference_score(summary, normalized_message),
                _same_usecase_score(summary, active_usecase),
                index,
                summary,
            )
        )

    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    budget = settings.context_summary.max_total_visualization_context_tokens
    max_items = settings.context_summary.max_chart_summaries_per_session_context

    selected_indices: list[int] = []
    total_tokens = 0
    for _, _, original_index, summary in scored:
        if len(selected_indices) >= max_items:
            break
        token_estimate = _summary_token_estimate(summary)
        if selected_indices and total_tokens + token_estimate > budget:
            continue
        if not selected_indices and token_estimate > budget:
            continue
        selected_indices.append(original_index)
        total_tokens += token_estimate

    selected_indices.sort()
    return tuple(summaries[index] for index in selected_indices)


def validate_chart_context_contribution(
    *,
    contribution: ContextContribution,
    settings: VisualizationSettings,
) -> ChartContextSummary | None:
    """Accept only prompt-safe chart summary contributions."""

    if contribution.kind != "chart_summary" or not contribution.include_in_next_prompt:
        return None
    try:
        summary = ChartContextSummary.model_validate(contribution.content)
    except ValidationError:
        return None
    return validate_chart_context_summary(summary, settings=settings)


def coerce_context_contribution(
    value: Mapping[str, Any],
) -> ContextContribution | None:
    """Build a contribution model from stored payloads, synthesizing missing token counts."""

    data = dict(value)
    if "token_estimate" not in data:
        summary = _coerce_chart_summary(data.get("content"))
        if summary is not None:
            data["token_estimate"] = _summary_token_estimate(summary)
            data.setdefault("source_artifact_id", summary.artifact_id)
    try:
        return ContextContribution.model_validate(data)
    except ValidationError:
        return None


def _resolve_visualization_context(container: object) -> Mapping[str, Any] | None:
    if not isinstance(container, Mapping):
        return None
    direct = container.get("visualization_context")
    if isinstance(direct, Mapping):
        return direct
    if any(key in container for key in _SUMMARY_KEYS):
        return container
    return None


def _iter_raw_summaries(visualization_context: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    for key in _SUMMARY_KEYS:
        raw_value = visualization_context.get(key)
        if not isinstance(raw_value, Sequence) or isinstance(raw_value, str | bytes | bytearray):
            continue
        items: list[Mapping[str, Any]] = []
        for item in raw_value:
            if isinstance(item, Mapping):
                items.append(item)
        if items:
            return tuple(items)
    return ()


def _coerce_chart_summary(value: object) -> ChartContextSummary | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return ChartContextSummary.model_validate(dict(value))
    except ValidationError:
        return None


def _with_usecase(summary: ChartContextSummary, *, active_usecase: str | None) -> ChartContextSummary:
    if active_usecase is None:
        return summary
    metadata = dict(summary.metadata)
    metadata.setdefault("usecase", active_usecase)
    return summary.model_copy(update={"metadata": metadata})


def _dedupe_latest(summaries: Sequence[ChartContextSummary]) -> tuple[ChartContextSummary, ...]:
    deduped: list[ChartContextSummary] = []
    seen: set[str] = set()
    for summary in reversed(summaries):
        if summary.artifact_id in seen:
            continue
        deduped.append(summary)
        seen.add(summary.artifact_id)
    deduped.reverse()
    return tuple(deduped)


def _select_for_storage(
    *,
    summaries: Sequence[ChartContextSummary],
    active_usecase: str | None,
    settings: VisualizationSettings,
) -> tuple[ChartContextSummary, ...]:
    if not settings.context_summary.enabled:
        return ()

    scored: list[tuple[int, int, ChartContextSummary]] = []
    for index, summary in enumerate(summaries):
        scored.append((_same_usecase_score(summary, active_usecase), index, summary))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    budget = settings.context_summary.max_total_visualization_context_tokens
    max_items = settings.context_summary.max_chart_summaries_per_session_context
    selected_indices: list[int] = []
    total_tokens = 0
    for _, original_index, summary in scored:
        if len(selected_indices) >= max_items:
            break
        token_estimate = _summary_token_estimate(summary)
        if selected_indices and total_tokens + token_estimate > budget:
            continue
        if not selected_indices and token_estimate > budget:
            continue
        selected_indices.append(original_index)
        total_tokens += token_estimate

    selected_indices.sort()
    return tuple(summaries[index] for index in selected_indices)


def _summary_token_estimate(summary: ChartContextSummary) -> int:
    return summary.token_estimate or estimate_chart_summary_tokens(summary)


def _same_usecase_score(summary: ChartContextSummary, active_usecase: str | None) -> int:
    if active_usecase is None:
        return 0
    usecase = summary.metadata.get("usecase")
    if isinstance(usecase, str) and usecase.strip() == active_usecase:
        return 1
    return 0


def _explicit_reference_score(summary: ChartContextSummary, normalized_message: str) -> int:
    if not normalized_message:
        return 0
    if summary.artifact_id.casefold() in normalized_message:
        return 3
    title = summary.title.casefold()
    if title and title in normalized_message:
        return 2
    if summary.chart_type.replace("_", " ") in normalized_message:
        return 1
    fields = [summary.x_field, *summary.y_fields, summary.series_field]
    for field_name in fields:
        if isinstance(field_name, str) and field_name.casefold() in normalized_message:
            return 1
    return 0


__all__ = [
    "collect_chart_summaries",
    "coerce_context_contribution",
    "merge_visualization_context",
    "select_chart_summaries_for_prompt",
    "validate_chart_context_contribution",
]