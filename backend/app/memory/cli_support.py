"""Shared backend-local helpers for docs memory CLI scripts."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.config.loader import load_validated_config, resolve_backend_path
from app.config.view import ValidatedConfigurationView
from app.contracts.errors import ConfigurationError
from app.contracts.memory import DocumentIngestRequest, MemoryScope
from app.memory.adapters.memory_store import MemoryStoreAdapter
from app.memory.errors import MemoryInvalidScopeError
from app.memory.scopes import ProjectScopeSettings, read_project_scope_settings, resolve_configured_project_id

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
DOCS_ROOT = REPO_ROOT / "docs"
DEFAULT_CONFIG_PATH = BACKEND_ROOT / "config" / "app.yaml"
DOCS_CLI_USECASE_NAME = "architecture_document_qa"
DOCS_CLI_CONFIGURED_AGENT_NAME = "architecture_document_agent"
_BACKEND_OWNED_MEMORY_ENV_KEYS = (
    "MEMORY_STORE_DB_PATH",
    "MEMORY_STORE_CONFIG",
    "MEMORY_STORE_CONFIG_PATH",
)


class MemoryCliError(RuntimeError):
    """Operator-facing CLI error with a stable process exit code."""

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True, slots=True)
class LoadedMemoryRuntime:
    """Resolved config and adapter state shared by the CLIs."""

    config_path: Path
    config: ValidatedConfigurationView
    adapter: MemoryStoreAdapter
    database_path: Path | None
    search_limit_default: int
    search_limit_max: int
    allow_writes: bool


@dataclass(frozen=True, slots=True)
class CliScopeResolution:
    """Resolved effective CLI scope and operator-facing resolution metadata."""

    scope: MemoryScope
    requested_scope: MemoryScope
    project_id_resolution: str | None
    user_id_resolution: str
    agent_id_resolution: str


async def load_memory_runtime(
    config_path: str | Path | None = None,
    *,
    require_writes: bool = False,
) -> LoadedMemoryRuntime:
    """Load validated backend config and initialize the configured memory adapter."""

    resolved_config_path = resolve_backend_path(config_path or DEFAULT_CONFIG_PATH)
    if resolved_config_path is None:
        raise MemoryCliError("Configuration path could not be resolved.", exit_code=2)

    try:
        parsed = load_validated_config(resolved_config_path)
    except ConfigurationError as exc:
        raise MemoryCliError(str(exc), exit_code=2) from exc

    config = ValidatedConfigurationView(parsed.model_dump(mode="python"))
    memory_settings = config.memory_settings()
    persistence_settings = config.persistence_settings().memory

    if not memory_settings.enabled:
        raise MemoryCliError(
            "Memory is disabled in the configured backend runtime.",
            exit_code=2,
        )

    if persistence_settings.provider != "memory_store":
        raise MemoryCliError(
            f"Configured memory provider is not memory_store: {persistence_settings.provider}",
            exit_code=2,
        )

    if require_writes and not persistence_settings.memory_store.allow_writes:
        raise MemoryCliError(
            "Memory writes are disabled in the configured backend runtime.",
            exit_code=2,
        )

    adapter = MemoryStoreAdapter(
        persistence_settings.memory_store,
        required=persistence_settings.required,
    )
    try:
        with _suppressed_backend_memory_env():
            await adapter.initialize()
    except Exception as exc:
        raise MemoryCliError(
            f"Failed to initialize configured memory_store adapter: {exc}",
            exit_code=1,
        ) from exc

    return LoadedMemoryRuntime(
        config_path=resolved_config_path,
        config=config,
        adapter=adapter,
        database_path=persistence_settings.memory_store.database_path,
        search_limit_default=persistence_settings.memory_store.search_limit_default,
        search_limit_max=persistence_settings.memory_store.search_limit_max,
        allow_writes=persistence_settings.memory_store.allow_writes,
    )


async def close_memory_runtime(runtime: LoadedMemoryRuntime) -> None:
    """Close the initialized adapter if the CLI opened one."""

    close_error: Exception | None = None
    try:
        await runtime.adapter.close()
    except Exception as exc:
        close_error = exc
    finally:
        _shutdown_embedded_memory_jvm()

    if close_error is not None:
        raise close_error


def resolve_docs_directory(
    subpath: str | Path | None = None,
    *,
    docs_root: Path = DOCS_ROOT,
) -> Path:
    """Resolve and validate a docs-root-relative directory."""

    resolved_docs_root = docs_root.resolve(strict=False)
    if subpath is None or str(subpath).strip() == "":
        candidate = resolved_docs_root
    else:
        candidate = resolved_docs_root / Path(subpath)

    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_docs_root)
    except ValueError as exc:
        raise MemoryCliError(
            f"Docs path must stay within repository docs/: {candidate}",
            exit_code=2,
        ) from exc

    if not resolved_candidate.exists():
        raise MemoryCliError(f"Docs path does not exist: {resolved_candidate}", exit_code=2)

    if not resolved_candidate.is_dir():
        raise MemoryCliError(
            f"Docs path is not a directory: {resolved_candidate}",
            exit_code=2,
        )

    return resolved_candidate


def discover_markdown_files(root: Path) -> list[Path]:
    """Enumerate recursive Markdown files under the provided docs directory."""

    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() == ".md"
    )


def build_cli_scope(
    *,
    project_id: str,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> MemoryScope:
    """Normalize CLI scope inputs into the backend memory scope model."""

    return MemoryScope(
        user_id=_normalized_text(user_id),
        project_id=_normalized_text(project_id),
        agent_name=_normalized_text(agent_id),
    )


def resolve_cli_scope(
    config: ValidatedConfigurationView,
    *,
    project_id: str | None,
    user_id: str | None = None,
    agent_id: str | None = None,
    usecase_name: str = DOCS_CLI_USECASE_NAME,
    configured_agent_name: str = DOCS_CLI_CONFIGURED_AGENT_NAME,
) -> CliScopeResolution:
    """Resolve CLI scope using the same configured project rules as runtime retrieval."""

    normalized_project_id = _normalized_text(project_id)
    normalized_user_id = _normalized_text(user_id)
    normalized_agent_id = _normalized_text(agent_id)
    requested_scope = MemoryScope(
        user_id=normalized_user_id,
        project_id=normalized_project_id,
        agent_name=normalized_agent_id,
    )

    try:
        settings = read_project_scope_settings(
            config,
            usecase_name=usecase_name,
            agent_name=configured_agent_name,
        )
        resolved_project_id, project_id_resolution = resolve_configured_project_id(
            explicit_project_id=normalized_project_id,
            settings=settings,
        )
    except MemoryInvalidScopeError as exc:
        raise MemoryCliError(str(exc), exit_code=2) from exc

    if resolved_project_id is None:
        raise MemoryCliError(
            "Docs CLI could not resolve an effective project_id; pass --project-id or configure "
            f"{usecase_name}.memory.allowed_project_ids/default_project_id and "
            f"{configured_agent_name}.memory.allowed_project_ids/default_project_id.",
            exit_code=2,
        )

    return CliScopeResolution(
        scope=build_cli_scope(
            project_id=resolved_project_id,
            user_id=normalized_user_id,
            agent_id=normalized_agent_id,
        ),
        requested_scope=requested_scope,
        project_id_resolution=project_id_resolution,
        user_id_resolution="explicit" if normalized_user_id is not None else "unset",
        agent_id_resolution="explicit" if normalized_agent_id is not None else "unset",
    )


def format_cli_scope_summary(resolution: CliScopeResolution) -> tuple[str, ...]:
    """Return compact operator-facing scope-resolution lines for local CLIs."""

    lines: list[str] = []
    resolved_project_id = resolution.scope.project_id
    if resolution.project_id_resolution == "explicit":
        lines.append(f"project_id provided explicitly: '{resolved_project_id}'.")
    elif resolution.project_id_resolution in {"usecase_default", "agent_default"}:
        lines.append(
            f"project_id not provided; using configured default '{resolved_project_id}'."
        )
    elif resolution.project_id_resolution == "singleton_intersection":
        lines.append(
            "project_id not provided; using the only allowed configured project "
            f"'{resolved_project_id}'."
        )
    else:
        lines.append(f"project_id resolved to '{resolved_project_id}'.")

    if resolution.user_id_resolution == "explicit":
        lines.append(f"user_id provided explicitly: '{resolution.scope.user_id}'.")
    else:
        lines.append("user_id not provided; scope will remain project-only.")

    if resolution.agent_id_resolution == "explicit":
        lines.append(f"agent_id provided explicitly: '{resolution.scope.agent_name}'.")
    else:
        lines.append("agent_id not provided; no agent-specific memory scope will be applied.")

    return tuple(lines)


def cli_scope_payload(scope: MemoryScope) -> dict[str, str]:
    """Return a stable JSON-safe scope payload for CLI results."""

    return {
        "user_id": scope.user_id or "",
        "project_id": scope.project_id or "",
        "agent_id": scope.agent_name or "",
    }


def cli_scope_resolution_payload(resolution: CliScopeResolution) -> dict[str, str]:
    """Return a stable JSON-safe resolution payload for CLI results."""

    return {
        "project_id": resolution.project_id_resolution or "",
        "user_id": resolution.user_id_resolution,
        "agent_id": resolution.agent_id_resolution,
    }


def as_repo_relative_path(path: Path, *, repo_root: Path = REPO_ROOT) -> str:
    """Return a stable repo-relative POSIX path for one repository file."""

    resolved_repo_root = repo_root.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    try:
        return resolved_path.relative_to(resolved_repo_root).as_posix()
    except ValueError as exc:
        raise MemoryCliError(
            f"Path must stay within repository root: {resolved_path}",
            exit_code=2,
        ) from exc


def build_document_ingest_request(
    path: Path,
    *,
    scope: MemoryScope,
    repo_root: Path = REPO_ROOT,
) -> DocumentIngestRequest:
    """Build a deterministic document-ingest request for one docs file."""

    resolved_path = path.resolve(strict=False)
    repo_relative_path = as_repo_relative_path(path, repo_root=repo_root)
    scope_metadata = dict(scope.metadata)
    scope_metadata.update(
        {
            "corpus": "docs",
            "repo_relative_path": repo_relative_path,
        }
    )

    request_scope = MemoryScope(
        user_id=scope.user_id,
        project_id=scope.project_id,
        tenant_id=scope.tenant_id,
        session_id=scope.session_id,
        agent_name=scope.agent_name,
        usecase=scope.usecase,
        source_id=repo_relative_path,
        document_id=repo_relative_path,
        tags=scope.tags,
        metadata=scope_metadata,
    )

    return DocumentIngestRequest(
        source_id=repo_relative_path,
        document_id=repo_relative_path,
        scope=request_scope,
        path=str(resolved_path),
        source_uri=repo_relative_path,
        title=path.stem,
        content_type="text/markdown",
        replace_existing=True,
        mark_missing_chunks_removed=True,
        metadata={
            "corpus": "docs",
            "repo_relative_path": repo_relative_path,
            "content_type": "text/markdown",
        },
    )


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _shutdown_embedded_memory_jvm() -> None:
    try:
        from arcadedb_embedded.jvm import shutdown_jvm
    except Exception:
        return

    try:
        shutdown_jvm()
    except Exception:
        return


@contextmanager
def _suppressed_backend_memory_env() -> Iterator[None]:
    hidden_values: dict[str, str] = {}
    for name in _BACKEND_OWNED_MEMORY_ENV_KEYS:
        current = os.environ.pop(name, None)
        if current is not None:
            hidden_values[name] = current

    try:
        yield
    finally:
        os.environ.update(hidden_values)