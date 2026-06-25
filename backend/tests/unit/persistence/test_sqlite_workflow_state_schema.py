from __future__ import annotations

from pathlib import Path

from app.contracts.state import WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE
from app.persistence.settings import SqliteWorkflowStateSettings
from app.persistence.sqlite.connection import open_sqlite_connection
from app.persistence.sqlite.migrations import get_schema_version
from app.persistence.sqlite_workflow_state_schema import (
    WORKFLOW_STATE_SCHEMA_NAME,
    WORKFLOW_STATE_SCHEMA_VERSION,
    ensure_workflow_state_schema,
)


def test_workflow_state_schema_initializer_is_idempotent_and_creates_expected_objects(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "workflow-state-schema.db"
    settings = SqliteWorkflowStateSettings(
        path=database_path,
        create_parent_dirs=True,
        initialize_schema=True,
        journal_mode="WAL",
        synchronous="NORMAL",
        busy_timeout_ms=5000,
        foreign_keys=True,
        required=True,
        max_state_bytes=1048576,
        max_history_messages=50,
        reset_mode=WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE,
        store_user_id=False,
        store_user_id_hash=True,
    )

    with open_sqlite_connection(database_path, settings=settings) as connection:
        ensure_workflow_state_schema(connection)
        ensure_workflow_state_schema(connection)
        connection.commit()

        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        indexes = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_workflow_%'"
            ).fetchall()
        }
        state_columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info('workflow_state_current')"
            ).fetchall()
        }

    assert tables >= {
        "schema_version",
        "workflow_sessions",
        "workflow_state_current",
        "workflow_state_resets",
    }
    assert indexes >= {
        "idx_workflow_sessions_user_hash",
        "idx_workflow_sessions_usecase",
        "idx_workflow_sessions_last_activity",
        "idx_workflow_state_updated_at",
        "idx_workflow_state_current_step",
        "idx_workflow_resets_session_id",
        "idx_workflow_resets_reset_at",
    }
    assert state_columns >= {
        "session_id",
        "state_version",
        "state_json",
        "state_hash",
        "state_size_bytes",
        "message_count",
        "current_step",
        "checkpoint_name",
        "created_at",
        "updated_at",
        "reset_generation",
    }
    assert get_schema_version_for_file(database_path) == WORKFLOW_STATE_SCHEMA_VERSION


def get_schema_version_for_file(database_path: Path) -> int | None:
    settings = SqliteWorkflowStateSettings(
        path=database_path,
        create_parent_dirs=True,
        initialize_schema=True,
        journal_mode="WAL",
        synchronous="NORMAL",
        busy_timeout_ms=5000,
        foreign_keys=True,
        required=True,
        max_state_bytes=1048576,
        max_history_messages=50,
        reset_mode=WORKFLOW_STATE_RESET_MODE_REPLACE_WITH_EMPTY_STATE,
        store_user_id=False,
        store_user_id_hash=True,
    )

    with open_sqlite_connection(database_path, settings=settings) as connection:
        return get_schema_version(connection, name=WORKFLOW_STATE_SCHEMA_NAME)