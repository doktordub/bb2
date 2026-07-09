from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WINDOWS = os.name == "nt"
MINIMUM_PYTHON = (3, 12)


@dataclass(frozen=True)
class TierProject:
    name: str
    directory: Path


TIERS = (
    TierProject("mcp", ROOT / "mcp"),
    TierProject("backend", ROOT / "backend"),
    TierProject("frontend", ROOT / "frontend"),
)


def _venv_python_path(tier_dir: Path) -> Path:
    if WINDOWS:
        return tier_dir / ".venv" / "Scripts" / "python.exe"
    return tier_dir / ".venv" / "bin" / "python"


def _run(command: list[str], *, cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def _ensure_python_compatible(python_executable: str) -> None:
    command = [
        python_executable,
        "-c",
        (
            "import sys; "
            f"raise SystemExit(0 if sys.version_info >= {MINIMUM_PYTHON} else 1)"
        ),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        version_text = exc.stdout.strip() or exc.stderr.strip() or "unknown"
        raise RuntimeError(
            "The selected Python interpreter must be 3.12 or newer. "
            f"Interpreter: {python_executable}. Reported version: {version_text}"
        ) from exc


def _create_venv_if_needed(project: TierProject, python_executable: str) -> Path:
    interpreter = _venv_python_path(project.directory)
    if interpreter.exists():
        print(f"[{project.name}] Reusing existing virtual environment.")
        return interpreter

    print(f"[{project.name}] Creating virtual environment...")
    _run([python_executable, "-m", "venv", ".venv"], cwd=project.directory)
    return interpreter


def _install_project(project: TierProject, python_executable: str, include_dev: bool) -> None:
    interpreter = _create_venv_if_needed(project, python_executable)

    print(f"[{project.name}] Upgrading pip tooling...")
    _run(
        [str(interpreter), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
        cwd=project.directory,
    )

    target = ".[dev]" if include_dev else "."
    print(f"[{project.name}] Installing {target}...")
    _run([str(interpreter), "-m", "pip", "install", "-e", target], cwd=project.directory)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create per-tier virtual environments and install Python dependencies.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used to create each tier virtual environment.",
    )
    parser.add_argument(
        "--tiers",
        nargs="+",
        choices=[tier.name for tier in TIERS],
        default=[tier.name for tier in TIERS],
        help="Subset of tiers to set up. Default: mcp backend frontend.",
    )
    parser.add_argument(
        "--no-dev",
        action="store_true",
        help="Install runtime dependencies only instead of editable dev dependencies.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    _ensure_python_compatible(args.python)

    requested = set(args.tiers)
    selected_projects = [tier for tier in TIERS if tier.name in requested]
    include_dev = not args.no_dev

    try:
        for project in selected_projects:
            _install_project(project, args.python, include_dev)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1

    print("Tier setup completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())