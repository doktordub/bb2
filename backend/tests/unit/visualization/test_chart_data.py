from __future__ import annotations

import pytest

from app.visualization.chart_data import normalize_chart_data
from app.visualization.errors import ChartDataValidationError


def test_normalize_chart_data_coerces_safe_numeric_strings() -> None:
    normalized = normalize_chart_data(
        [
            {"month": "2026-01", "revenue": "1200"},
            {"month": "2026-02", "revenue": 1350},
        ]
    )

    assert normalized.field_profiles["month"].kind == "temporal"
    assert normalized.field_profiles["revenue"].kind == "numeric"
    assert normalized.rows_as_list() == [
        {"month": "2026-01", "revenue": 1200},
        {"month": "2026-02", "revenue": 1350},
    ]


def test_normalize_chart_data_rejects_ambiguous_numeric_text_mix() -> None:
    with pytest.raises(ChartDataValidationError, match="mixes numeric"):
        normalize_chart_data(
            [
                {"segment": "Enterprise", "value": "620"},
                {"segment": "SMB", "value": "unknown"},
            ]
        )