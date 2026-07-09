from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WINDOWS = os.name == "nt"


@dataclass(frozen=True)
class TierConfig:
    name: str
    directory: Path
    module_args: tuple[str, ...]
    host: str
    port: int


TIERS = (
    TierConfig(
        name="mcp",
        directory=ROOT / "mcp",
        module_args=("-m", "app.main"),
        host="127.0.0.1",
        port=9001,
    ),
    TierConfig(
        name="backend",
        directory=ROOT / "backend",
        module_args=(
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ),
        host="127.0.0.1",
        port=8000,
    ),
    TierConfig(
        name="frontend",
        directory=ROOT / "frontend",
        module_args=("-m", "app.main"),
        host="127.0.0.1",
        port=5000,
    ),
)


def _venv_python_path(tier_dir: Path) -> Path:
    if WINDOWS:
        return tier_dir / ".venv" / "Scripts" / "python.exe"
    return tier_dir / ".venv" / "bin" / "python"


def _require_venv(tier: TierConfig) -> Path:
    interpreter = _venv_python_path(tier.directory)
    if not interpreter.exists():
        raise FileNotFoundError(
            f"{tier.name} virtual environment is missing: {interpreter}. "
            "Run `python setup.py` from the repository root first."
        )
    return interpreter


def _stream_output(prefix: str, stream: object) -> None:
    if stream is None:
        return

    for line in iter(stream.readline, ""):
        print(f"[{prefix}] {line.rstrip()}")


def _wait_for_port(host: str, port: int, process: subprocess.Popen[str], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Process exited before becoming ready on {host}:{port}.")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return

        time.sleep(0.25)

    raise TimeoutError(f"Timed out waiting for {host}:{port} to accept connections.")


def _launch_tier(tier: TierConfig, timeout: float) -> subprocess.Popen[str]:
    interpreter = _require_venv(tier)
    command = [str(interpreter), *tier.module_args]
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    process = subprocess.Popen(
        command,
        cwd=tier.directory,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    thread = threading.Thread(
        target=_stream_output,
        args=(tier.name, process.stdout),
        daemon=True,
    )
    thread.start()

    _wait_for_port(tier.host, tier.port, process, timeout)
    print(f"[{tier.name}] Ready on http://{tier.host}:{tier.port}")
    return process


def _terminate_processes(processes: list[tuple[TierConfig, subprocess.Popen[str]]]) -> None:
    for tier, process in reversed(processes):
        if process.poll() is not None:
            continue
        print(f"Stopping {tier.name}...")
        process.terminate()

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if all(process.poll() is not None for _, process in processes):
            return
        time.sleep(0.25)

    for tier, process in reversed(processes):
        if process.poll() is not None:
            continue
        print(f"Force killing {tier.name}...")
        process.kill()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start MCP, backend, and frontend in dependency order.",
    )
    parser.add_argument(
        "--tiers",
        nargs="+",
        choices=[tier.name for tier in TIERS],
        default=[tier.name for tier in TIERS],
        help="Subset of tiers to start. Default: all tiers in dependency order.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for each tier to accept connections.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    selected_names = set(args.tiers)
    selected_tiers = [tier for tier in TIERS if tier.name in selected_names]
    processes: list[tuple[TierConfig, subprocess.Popen[str]]] = []

    try:
        for tier in selected_tiers:
            print(f"Starting {tier.name} from {tier.directory}...")
            process = _launch_tier(tier, args.timeout)
            processes.append((tier, process))

        print("All requested tiers are running. Press Ctrl+C to stop them.")

        while True:
            for tier, process in processes:
                exit_code = process.poll()
                if exit_code is not None:
                    raise RuntimeError(f"{tier.name} exited unexpectedly with code {exit_code}.")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Shutdown requested.")
        return 0
    except Exception as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1
    finally:
        _terminate_processes(processes)


if __name__ == "__main__":
    raise SystemExit(main())