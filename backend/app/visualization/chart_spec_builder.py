"""Deterministic builder for frontend-facing chart artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from app.visualization.chart_data import NormalizedChartData, normalize_chart_data, validate_chart_field_name
from app.visualization.chart_registry import ChartTypeRegistry
from app.visualization.errors import ChartArtifactBuildError, ChartEncodingError, ChartRowLimitExceededError
from app.visualization.models import ChartArtifact, ChartDataMode, ChartRequest, ChartRenderer, VisualizationContext
from app.visualization.renderer_capabilities import RendererCapabilityCatalog
from app.visualization.settings import VisualizationSettings
from app.visualization.validators import validate_chart_artifact

_STRUCTURAL_OPTION_KEYS = frozenset({"size_field", "y_field", "start_field", "end_field", "task_field"})


@dataclass(slots=True)
class ChartSpecBuilder:
    """Build validated renderer-neutral chart artifacts from normalized inputs."""

    settings: VisualizationSettings
    registry: ChartTypeRegistry
    capability_catalog: RendererCapabilityCatalog

    def build(
        self,
        *,
        request: ChartRequest,
        data: Sequence[Mapping[str, Any]] | NormalizedChartData,
        context: VisualizationContext,
        metadata: Mapping[str, Any] | None = None,
        warnings: Sequence[str] | None = None,
        artifact_id: str | None = None,
        data_ref: str | None = None,
    ) -> ChartArtifact:
        """Build one validated chart artifact for the frontend delivery channel."""

        self.registry.get(request.chart_type)
        normalized = data if isinstance(data, NormalizedChartData) else normalize_chart_data(data)
        encoding = _build_encoding(request)
        normalized_metadata = _build_metadata(
            request=request,
            metadata=metadata,
            allowlist=self.settings.safe_metadata_allowlist,
        )
        normalized_options = _build_options(request)
        normalized_warnings = _normalize_warnings(normalized.warnings, warnings)
        resolved_artifact_id = artifact_id or _build_artifact_id(
            request=request,
            normalized=normalized,
            encoding=encoding,
            context=context,
            renderer=self.settings.default_renderer,
            spec_version=self.settings.artifact_spec_version,
        )

        inline_artifact = self._build_inline_artifact(
            request=request,
            normalized=normalized,
            artifact_id=resolved_artifact_id,
            encoding=encoding,
            options=normalized_options,
            metadata=normalized_metadata,
            warnings=normalized_warnings,
        )

        if self._should_use_reference_mode(normalized=normalized, artifact=inline_artifact):
            if not self._supports_reference_mode(chart_type=request.chart_type):
                raise ChartRowLimitExceededError(
                    "The dataset is too large to return inline. Please filter or summarize it first."
                )
            return self._build_reference_artifact(
                request=request,
                artifact_id=resolved_artifact_id,
                encoding=encoding,
                options=normalized_options,
                metadata=normalized_metadata,
                warnings=normalized_warnings,
                context=context,
                data_ref=data_ref,
            )

        try:
            return validate_chart_artifact(
                inline_artifact,
                settings=self.settings,
                registry=self.registry,
                capability_catalog=self.capability_catalog,
            )
        except ChartEncodingError as exc:
            if self._is_artifact_size_error(exc) and self._supports_reference_mode(chart_type=request.chart_type):
                return self._build_reference_artifact(
                    request=request,
                    artifact_id=resolved_artifact_id,
                    encoding=encoding,
                    options=normalized_options,
                    metadata=normalized_metadata,
                    warnings=normalized_warnings,
                    context=context,
                    data_ref=data_ref,
                )
            raise

    def _build_inline_artifact(
        self,
        *,
        request: ChartRequest,
        normalized: NormalizedChartData,
        artifact_id: str,
        encoding: dict[str, Any],
        options: dict[str, Any],
        metadata: dict[str, Any],
        warnings: list[str],
    ) -> ChartArtifact:
        return ChartArtifact(
            artifact_id=artifact_id,
            chart_type=request.chart_type,
            title=request.title,
            description=request.description,
            renderer=cast(ChartRenderer, self.settings.default_renderer),
            spec_version=self.settings.artifact_spec_version,
            data_mode=cast(ChartDataMode, "inline"),
            data=normalized.rows_as_list(),
            data_ref=None,
            encoding=encoding,
            options=options,
            warnings=warnings,
            metadata=metadata,
        )

    def _build_reference_artifact(
        self,
        *,
        request: ChartRequest,
        artifact_id: str,
        encoding: dict[str, Any],
        options: dict[str, Any],
        metadata: dict[str, Any],
        warnings: list[str],
        context: VisualizationContext,
        data_ref: str | None,
    ) -> ChartArtifact:
        artifact = ChartArtifact(
            artifact_id=artifact_id,
            chart_type=request.chart_type,
            title=request.title,
            description=request.description,
            renderer=cast(ChartRenderer, self.settings.default_renderer),
            spec_version=self.settings.artifact_spec_version,
            data_mode=cast(ChartDataMode, "reference"),
            data=None,
            data_ref=data_ref or _build_data_ref(context=context, artifact_id=artifact_id),
            encoding=encoding,
            options=options,
            warnings=warnings,
            metadata=metadata,
        )
        return validate_chart_artifact(
            artifact,
            settings=self.settings,
            registry=self.registry,
            capability_catalog=self.capability_catalog,
        )

    def _should_use_reference_mode(
        self,
        *,
        normalized: NormalizedChartData,
        artifact: ChartArtifact,
    ) -> bool:
        if normalized.row_count > self.settings.limits.max_rows_artifact_store:
            raise ChartRowLimitExceededError(
                "The dataset exceeds the configured visualization row limit."
            )
        if normalized.row_count > self.settings.limits.max_rows_inline:
            return True
        return _encoded_artifact_size(artifact) > self.settings.limits.max_artifact_bytes

    def _supports_reference_mode(self, *, chart_type: str) -> bool:
        return self.capability_catalog.supports(
            renderer=self.settings.default_renderer,
            chart_type=chart_type,
            spec_version=self.settings.artifact_spec_version,
            data_mode="reference",
        )

    @staticmethod
    def _is_artifact_size_error(error: ChartEncodingError) -> bool:
        return "size limit" in str(error).lower()


def _build_encoding(request: ChartRequest) -> dict[str, Any]:
    chart_type = request.chart_type

    if chart_type in {"bar", "horizontal_bar", "line", "area", "radar", "box_plot"}:
        x_field = _required_field(request.x_field or request.category_field, label="x_field")
        y_fields = _required_y_fields(request)
        encoding: dict[str, Any] = {"x": x_field, "y": y_fields}
        if request.time_field:
            encoding["time"] = validate_chart_field_name(request.time_field)
        return encoding

    if chart_type in {"grouped_bar", "stacked_bar", "multi_line"}:
        x_field = _required_field(request.x_field or request.category_field, label="x_field")
        encoding = {"x": x_field}
        if request.time_field:
            encoding["time"] = validate_chart_field_name(request.time_field)
        if request.y_fields:
            encoding["y"] = [validate_chart_field_name(field_name) for field_name in request.y_fields]
            return encoding
        if request.series_field and request.value_field:
            encoding["series"] = validate_chart_field_name(request.series_field)
            encoding["value"] = validate_chart_field_name(request.value_field)
            return encoding
        raise ChartArtifactBuildError(
            f"{chart_type} charts require multiple y fields or a series/value encoding pair."
        )

    if chart_type in {"pie", "donut", "treemap"}:
        return {
            "category": _required_field(request.category_field or request.x_field, label="category_field"),
            "value": _required_value_field(request),
        }

    if chart_type == "waterfall":
        return {
            "x": _required_field(request.x_field or request.category_field, label="x_field"),
            "value": _required_value_field(request),
        }

    if chart_type == "scatter":
        return {
            "x": _required_field(request.x_field, label="x_field"),
            "y": _required_scalar_y_field(request),
        }

    if chart_type == "bubble":
        size_field = _required_option_field(request, option_key="size_field")
        return {
            "x": _required_field(request.x_field, label="x_field"),
            "y": _required_scalar_y_field(request),
            "size": size_field,
        }

    if chart_type == "histogram":
        return {
            "x": _required_field(request.x_field or request.value_field or _first_y_field(request), label="x_field"),
        }

    if chart_type == "heatmap":
        return {
            "x": _required_field(request.x_field, label="x_field"),
            "y": _required_field(request.series_field or _read_option_field(request, "y_field"), label="y_field"),
            "value": _required_value_field(request),
        }

    if chart_type == "gantt":
        task_field = _required_field(
            request.x_field or request.category_field or _read_option_field(request, "task_field"),
            label="task_field",
        )
        return {
            "task": task_field,
            "start": _required_option_field(request, option_key="start_field"),
            "end": _required_option_field(request, option_key="end_field"),
        }

    if chart_type == "table":
        return {}

    raise ChartArtifactBuildError(f"Unsupported chart type '{chart_type}'.")


def _build_artifact_id(
    *,
    request: ChartRequest,
    normalized: NormalizedChartData,
    encoding: Mapping[str, Any],
    context: VisualizationContext,
    renderer: str,
    spec_version: str,
) -> str:
    identity = {
        "chart_type": request.chart_type,
        "title": request.title,
        "description": request.description,
        "encoding": encoding,
        "options": _build_options(request),
        "rows": normalized.rows,
        "renderer": renderer,
        "session_id": context.session_id,
        "spec_version": spec_version,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return f"chart_{digest[:16]}"


def _build_data_ref(*, context: VisualizationContext, artifact_id: str) -> str:
    return f"artifact://{context.session_id}/{artifact_id}"


def _build_metadata(
    *,
    request: ChartRequest,
    metadata: Mapping[str, Any] | None,
    allowlist: Sequence[str],
) -> dict[str, Any]:
    normalized: dict[str, Any] = {"source": request.data_source}
    if metadata is None:
        return normalized

    allowed_keys = set(allowlist)
    for key, value in metadata.items():
        normalized_key = validate_chart_field_name(key)
        if normalized_key not in allowed_keys:
            continue
        normalized_value = _normalize_json_value(value)
        if normalized_value is not None:
            normalized[normalized_key] = normalized_value
    return normalized


def _build_options(request: ChartRequest) -> dict[str, Any]:
    options = {
        validate_chart_field_name(key): _normalize_json_value(value)
        for key, value in request.options.items()
        if validate_chart_field_name(key) not in _STRUCTURAL_OPTION_KEYS
    }
    normalized_options = {key: value for key, value in options.items() if value is not None}
    if request.chart_type == "stacked_bar":
        normalized_options.setdefault("stacked", True)
    if request.chart_type == "horizontal_bar":
        normalized_options.setdefault("orientation", "horizontal")
    return normalized_options


def _normalize_warnings(*warning_groups: Sequence[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for warning_group in warning_groups:
        if warning_group is None:
            continue
        for warning in warning_group:
            text = str(warning).strip()
            if text and text not in seen:
                normalized.append(text)
                seen.add(text)
    return normalized[:8]


def _normalize_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return value
    if hasattr(value, "isoformat") and callable(value.isoformat):
        return value.isoformat()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {
            validate_chart_field_name(str(key)): _normalize_json_value(item)
            for key, item in value.items()
        }
    return str(value)


def _required_field(value: str | None, *, label: str) -> str:
    if value is None:
        raise ChartArtifactBuildError(f"Chart requests must include '{label}'.")
    return validate_chart_field_name(value)


def _required_y_fields(request: ChartRequest) -> list[str]:
    if not request.y_fields:
        if request.value_field is None:
            raise ChartArtifactBuildError("Chart requests must include at least one y field.")
        return [validate_chart_field_name(request.value_field)]
    return [validate_chart_field_name(field_name) for field_name in request.y_fields]


def _first_y_field(request: ChartRequest) -> str | None:
    return request.y_fields[0] if request.y_fields else None


def _required_scalar_y_field(request: ChartRequest) -> str:
    if request.y_fields:
        if len(request.y_fields) != 1:
            raise ChartArtifactBuildError("Scatter and bubble charts require exactly one y field.")
        return validate_chart_field_name(request.y_fields[0])
    if request.value_field is not None:
        return validate_chart_field_name(request.value_field)
    raise ChartArtifactBuildError("Scatter and bubble charts require exactly one y field.")


def _required_value_field(request: ChartRequest) -> str:
    if request.value_field is not None:
        return validate_chart_field_name(request.value_field)
    if len(request.y_fields) == 1:
        return validate_chart_field_name(request.y_fields[0])
    raise ChartArtifactBuildError("The chart request must include one numeric value field.")


def _required_option_field(request: ChartRequest, *, option_key: str) -> str:
    value = _read_option_field(request, option_key)
    if value is None:
        raise ChartArtifactBuildError(f"Chart requests must include '{option_key}'.")
    return value


def _read_option_field(request: ChartRequest, option_key: str) -> str | None:
    raw_value = request.options.get(option_key)
    if raw_value is None:
        return None
    return validate_chart_field_name(raw_value)


def _encoded_artifact_size(artifact: ChartArtifact) -> int:
    return len(
        json.dumps(
            artifact.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


__all__ = ["ChartSpecBuilder"]