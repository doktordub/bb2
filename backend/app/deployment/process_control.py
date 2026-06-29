"""Backend-owned restart control for local debug automation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import inspect
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any, Protocol
from uuid import uuid4


class RestartUnavailableError(RuntimeError):
    """Raised when restart was requested without a configured runtime handler."""


class ShutdownHandler(Protocol):
    def __call__(self) -> object:
        """Request runtime-specific restart handoff through the active runtime."""


@dataclass(frozen=True, slots=True)
class RestartLaunchSpec:
    """Launch metadata used to bring the backend back after shutdown."""

    command: tuple[str, ...]
    working_dir: str


@dataclass(frozen=True, slots=True)
class RestartRequestReceipt:
    """Safe receipt returned when the backend accepts a restart request."""

    request_id: str
    requested_at: str
    signal_path: str
    restart_requested: bool
    metadata: Mapping[str, Any]


class ProcessControlService:
    """Own restart request recording and runtime restart handoff."""

    def __init__(
        self,
        *,
        runtime_dir: Path,
        shutdown_handler: ShutdownHandler | None = None,
    ) -> None:
        self._runtime_dir = runtime_dir
        self._shutdown_handler = shutdown_handler

    @property
    def restart_supported(self) -> bool:
        return self._shutdown_handler is not None

    @property
    def signal_path(self) -> Path:
        return self._runtime_dir / "restart-request.json"

    def with_shutdown_handler(self, shutdown_handler: ShutdownHandler | None) -> ProcessControlService:
        """Return a new service instance bound to one runtime shutdown hook."""

        return ProcessControlService(
            runtime_dir=self._runtime_dir,
            shutdown_handler=shutdown_handler,
        )

    def prepare_restart_request(
        self,
        *,
        trace_id: str,
        requested_by: str | None,
        client_host: str | None,
        reason: str | None = None,
        route_path: str = "/restart",
    ) -> RestartRequestReceipt:
        """Persist a restart handoff record and return a safe public receipt."""

        self._require_restart_supported()
        self._runtime_dir.mkdir(parents=True, exist_ok=True)

        request_id = f"restart_{uuid4().hex}"
        requested_at = datetime.now(UTC).isoformat()
        payload = {
            "request_id": request_id,
            "requested_at": requested_at,
            "trace_id": trace_id,
            "requested_by": requested_by,
            "client_host": client_host,
            "reason": reason,
            "route_path": route_path,
            "graceful_shutdown_requested": True,
        }
        _write_json_atomic(self.signal_path, payload)

        metadata = {
            "graceful_shutdown_requested": True,
            "reason": reason,
        }
        return RestartRequestReceipt(
            request_id=request_id,
            requested_at=requested_at,
            signal_path=self.signal_path.as_posix(),
            restart_requested=True,
            metadata=metadata,
        )

    async def dispatch_restart(self) -> None:
        """Invoke the configured runtime restart hook after the response is sent."""

        shutdown_handler = self._require_restart_supported()
        result = shutdown_handler()
        if inspect.isawaitable(result):
            await result

    def _require_restart_supported(self) -> ShutdownHandler:
        shutdown_handler = self._shutdown_handler
        if shutdown_handler is None:
            raise RestartUnavailableError(
                "Backend restart is not configured for the current runtime."
            )
        return shutdown_handler


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    temp_path.replace(path)


def build_self_relaunch_handler(
    *,
    launch_spec: RestartLaunchSpec,
    shutdown_signal: int,
) -> ShutdownHandler:
    """Build a runtime hook that relaunches the backend before graceful shutdown."""

    def _request_restart() -> None:
        _spawn_restart_helper(launch_spec=launch_spec, parent_pid=os.getpid())
        signal.raise_signal(shutdown_signal)

    return _request_restart


def _spawn_restart_helper(*, launch_spec: RestartLaunchSpec, parent_pid: int) -> None:
    helper_command = _build_restart_helper_command(
        launch_spec=launch_spec,
        parent_pid=parent_pid,
    )
    popen_kwargs = _detached_popen_kwargs(working_dir=launch_spec.working_dir)
    subprocess.Popen(helper_command, **popen_kwargs)


def _build_restart_helper_command(
    *,
    launch_spec: RestartLaunchSpec,
    parent_pid: int,
) -> tuple[str, ...]:
    helper_python = _resolve_restart_helper_python(launch_spec.command)
    return (
        helper_python,
        "-m",
        "app.deployment.restart_helper",
        "--parent-pid",
        str(parent_pid),
        "--cwd",
        launch_spec.working_dir,
        "--",
        *launch_spec.command,
    )


def _resolve_restart_helper_python(command: tuple[str, ...]) -> str:
    if _looks_like_python_launcher_command(command):
        return command[0]
    return sys.executable


def _looks_like_python_launcher_command(command: tuple[str, ...]) -> bool:
    if not command:
        return False
    executable_name = Path(command[0]).name.lower()
    return executable_name in {"python", "python.exe", "py", "py.exe"}


def _detached_popen_kwargs(*, working_dir: str) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "cwd": working_dir,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = _windows_detached_creation_flags()
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _windows_detached_creation_flags() -> int:
    flags = 0
    for flag_name in (
        "DETACHED_PROCESS",
        "CREATE_NEW_PROCESS_GROUP",
        "CREATE_BREAKAWAY_FROM_JOB",
    ):
        flags |= getattr(subprocess, flag_name, 0)
    return flags