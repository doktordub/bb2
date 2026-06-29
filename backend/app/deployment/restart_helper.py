"""Detached helper that relaunches the backend after the current process exits."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import time
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    _wait_for_process_exit(args.parent_pid)
    _launch_replacement(command=args.command, working_dir=args.cwd)
    return 0


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--cwd", type=str, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        raise SystemExit("restart helper requires a launch command")
    return args


def _wait_for_process_exit(parent_pid: int) -> None:
    if os.name == "nt":
        _wait_for_process_exit_windows(parent_pid)
        return
    _wait_for_process_exit_poll(parent_pid)


def _wait_for_process_exit_windows(parent_pid: int) -> None:
    import ctypes

    process_synchronize = 0x00100000
    wait_object_0 = 0x00000000
    wait_failed = 0xFFFFFFFF
    kernel32 = ctypes.windll.kernel32

    process_handle = kernel32.OpenProcess(process_synchronize, False, parent_pid)
    if not process_handle:
        return
    try:
        result = kernel32.WaitForSingleObject(process_handle, 60000)
        if result in {wait_object_0, wait_failed}:
            return
    finally:
        kernel32.CloseHandle(process_handle)


def _wait_for_process_exit_poll(parent_pid: int) -> None:
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        try:
            os.kill(parent_pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            return
        time.sleep(0.1)


def _launch_replacement(*, command: Sequence[str], working_dir: str) -> None:
    launch_kwargs = _detached_popen_kwargs(working_dir=str(Path(working_dir)))
    subprocess.Popen(list(command), **launch_kwargs)


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


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())