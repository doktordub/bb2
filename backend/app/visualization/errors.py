"""Visualization-specific error taxonomy for the backend chart slice."""

from __future__ import annotations

from app.contracts.errors import BackendError, PolicyDeniedError


class VisualizationError(BackendError):
    """Base exception for backend-owned visualization failures."""


class UnsupportedChartTypeError(VisualizationError):
    """Raised when the requested canonical chart type is not supported."""

    def __init__(self, requested_type: str, supported_types: tuple[str, ...] | list[str]) -> None:
        self.requested_type = requested_type
        self.supported_types = tuple(supported_types)
        supported = ", ".join(self.supported_types)
        super().__init__(
            f"Unsupported chart type '{requested_type}'. Supported chart types: {supported}."
        )


class UnsupportedRendererError(VisualizationError):
    """Raised when the configured or requested renderer is not supported."""

    def __init__(self, renderer: str, supported_renderers: tuple[str, ...] | list[str]) -> None:
        self.renderer = renderer
        self.supported_renderers = tuple(supported_renderers)
        supported = ", ".join(self.supported_renderers)
        super().__init__(
            f"Unsupported renderer '{renderer}'. Supported renderers: {supported}."
        )


class ChartDataMissingError(VisualizationError):
    """Raised when visualization generation requires data that is unavailable."""


class ChartDataValidationError(VisualizationError):
    """Raised when chart input data does not satisfy visualization constraints."""


class ChartEncodingError(VisualizationError):
    """Raised when chart encoding fields or options are invalid."""


class ChartPolicyDeniedError(PolicyDeniedError, VisualizationError):
    """Raised when policy blocks visualization generation or retrieval."""


class ChartRowLimitExceededError(ChartDataValidationError):
    """Raised when a chart dataset exceeds configured row limits."""


class ChartSeriesLimitExceededError(ChartDataValidationError):
    """Raised when a chart request exceeds configured series limits."""


class ChartArtifactBuildError(VisualizationError):
    """Raised when the backend cannot construct a frontend chart artifact."""


class ChartContextSummaryBuildError(VisualizationError):
    """Raised when the backend cannot construct a bounded chart summary."""


class ChartContextSummaryLimitExceededError(ChartContextSummaryBuildError):
    """Raised when a chart summary exceeds the configured context budget."""


class ChartArtifactNotFoundError(VisualizationError):
    """Raised when a session-scoped chart artifact cannot be retrieved."""


class ChartFollowupAmbiguousError(VisualizationError):
    """Raised when a follow-up question cannot be mapped to one chart deterministically."""