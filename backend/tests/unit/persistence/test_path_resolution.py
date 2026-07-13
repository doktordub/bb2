from __future__ import annotations

from pathlib import Path

from app.config.view import ValidatedConfigurationView
from app.persistence.paths import resolve_backend_path, resolve_data_path
from app.persistence.settings import get_persistence_settings


def test_resolve_data_path_uses_configured_base_dir() -> None:
    base_dir = resolve_backend_path("data/runtime")

    assert resolve_data_path("trace.db", base_dir=base_dir) == base_dir / "trace.db"
    assert resolve_data_path(Path("workflow_state.db"), base_dir=base_dir) == base_dir / "workflow_state.db"


def test_persistence_paths_do_not_depend_on_current_working_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    view = ValidatedConfigurationView(
        {
            "app": {"data_dir": "./data"},
            "memory": {
                "store": {
                    "fastembed": {
                        "cache_dir": "./llm",
                    }
                }
            },
            "observability": {"max_trace_payload_chars": 8000},
            "persistence": {
                "base_dir": "./data",
                "workflow_state": {
                    "provider": "sqlite",
                    "sqlite": {
                        "path": "workflow_state.db",
                    },
                },
                "trace": {
                    "provider": "sqlite",
                    "sqlite": {
                        "path": "trace.db",
                    },
                },
                "memory": {
                    "provider": "memory_store",
                    "memory_store": {
                        "database_path": "memory",
                    },
                },
            },
        }
    )

    settings = get_persistence_settings(view)

    assert settings.base_dir == resolve_backend_path("./data")
    assert settings.workflow_state.sqlite is not None
    assert settings.workflow_state.sqlite.path == resolve_backend_path("data/workflow_state.db")
    assert settings.trace.sqlite is not None
    assert settings.trace.sqlite.path == resolve_backend_path("data/trace.db")
    assert settings.memory.memory_store.database_path == resolve_backend_path("data/memory")
    assert settings.memory.memory_store.fastembed_cache_path == resolve_backend_path("./llm")