"""SQLite schema bootstrap for durable visualization artifact persistence."""

from __future__ import annotations

from app.persistence.sqlite.migrations import SupportsMigration, ensure_schema

VISUALIZATION_ARTIFACT_SCHEMA = """
CREATE TABLE IF NOT EXISTS visualization_artifacts (
    session_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    user_id TEXT NULL,
    tenant_id TEXT NULL,
    project_id TEXT NULL,
    artifact_json TEXT NOT NULL,
    context_summary_json TEXT NOT NULL,
    rows_json TEXT NOT NULL DEFAULT '[]',
    fields_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    data_ref TEXT NULL,
    PRIMARY KEY (session_id, artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_visualization_artifacts_expires_at
    ON visualization_artifacts(expires_at);

CREATE INDEX IF NOT EXISTS idx_visualization_artifacts_created_at
    ON visualization_artifacts(created_at);

CREATE INDEX IF NOT EXISTS idx_visualization_artifacts_session_scope
    ON visualization_artifacts(session_id, user_id, tenant_id, project_id);
"""

VISUALIZATION_ARTIFACT_SCHEMA_NAME = "visualization_artifact_store"
VISUALIZATION_ARTIFACT_SCHEMA_VERSION = 1


def ensure_visualization_artifact_schema(connection: SupportsMigration) -> None:
    """Create the visualization artifact schema when it is missing."""

    ensure_schema(
        connection,
        name=VISUALIZATION_ARTIFACT_SCHEMA_NAME,
        target_version=VISUALIZATION_ARTIFACT_SCHEMA_VERSION,
        apply_schema=_apply_visualization_artifact_schema,
    )


def _apply_visualization_artifact_schema(connection: SupportsMigration) -> None:
    connection.executescript(VISUALIZATION_ARTIFACT_SCHEMA)


__all__ = [
    "VISUALIZATION_ARTIFACT_SCHEMA_NAME",
    "VISUALIZATION_ARTIFACT_SCHEMA_VERSION",
    "ensure_visualization_artifact_schema",
]