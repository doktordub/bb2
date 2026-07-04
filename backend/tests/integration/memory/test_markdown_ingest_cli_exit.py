from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import textwrap


BACKEND_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = BACKEND_ROOT / "scripts"


def test_markdown_ingest_cli_main_exits_successfully_after_ingest(
    tmp_path: Path,
) -> None:
    docs_root = tmp_path / "docs"
    docs_root.mkdir(parents=True)
    (docs_root / "alpha.md").write_text("# Alpha\n", encoding="utf-8")

    driver_path = tmp_path / "run_markdown_ingest_cli.py"
    driver_path.write_text(
        textwrap.dedent(
            f"""
            from __future__ import annotations

            import importlib.util
            from pathlib import Path
            import sys
            from types import ModuleType, SimpleNamespace

            from app.contracts.memory import MemoryScope
            from app.memory.cli_support import CliScopeResolution
            from app.testing.fakes import FakeConfigurationView


            backend_root = Path({str(BACKEND_ROOT)!r})
            scripts_dir = Path({str(SCRIPTS_DIR)!r})
            docs_root = Path({str(docs_root)!r})

            if str(backend_root) not in sys.path:
                sys.path.insert(0, str(backend_root))

            package = ModuleType("arcadedb_embedded")
            jvm_module = ModuleType("arcadedb_embedded.jvm")
            jvm_module.shutdown_jvm = lambda: None
            package.jvm = jvm_module
            sys.modules["arcadedb_embedded"] = package
            sys.modules["arcadedb_embedded.jvm"] = jvm_module

            spec = importlib.util.spec_from_file_location(
                "markdown_folder_ingest_cli_test",
                scripts_dir / "markdown_folder_ingest_cli.py",
            )
            assert spec is not None
            assert spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)


            class FakeAdapter:
                async def ingest_document(self, request: object) -> object:
                    return SimpleNamespace(
                        chunks_created=1,
                        chunks_updated=0,
                        chunks_removed=0,
                        chunks_unchanged=0,
                    )

                async def close(self) -> None:
                    return None


            async def fake_load_memory_runtime(*args: object, **kwargs: object) -> object:
                return SimpleNamespace(
                    adapter=FakeAdapter(),
                    database_path=docs_root / "memory-store",
                    config=FakeConfigurationView({{}}),
                )


            def fake_build_document_ingest_request(path: Path, *, scope: object) -> object:
                repo_path = path.relative_to(docs_root).as_posix()
                return SimpleNamespace(
                    source_uri=f"docs/{{repo_path}}",
                    source_id=f"docs/{{repo_path}}",
                    document_id=f"docs/{{repo_path}}",
                    scope=scope,
                )


            module.parse_args = lambda: SimpleNamespace(
                docs_subpath=None,
                config_path=Path("config/app.yaml"),
                user_id="",
                project_id="docs",
                agent_id="",
                fail_fast=False,
            )
            module.load_memory_runtime = fake_load_memory_runtime
            module.resolve_cli_scope = lambda *args, **kwargs: CliScopeResolution(
                scope=MemoryScope(project_id="arch_docs"),
                requested_scope=MemoryScope(),
                project_id_resolution="usecase_default",
                user_id_resolution="unset",
                agent_id_resolution="unset",
            )
            module.resolve_docs_directory = lambda subpath: docs_root
            module.discover_markdown_files = lambda root: [docs_root / "alpha.md"]
            module.build_document_ingest_request = fake_build_document_ingest_request

            raise SystemExit(module.main())
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(driver_path)],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["processed_files"] == 1
    assert payload["failed_files"] == 0
    assert payload["scope"]["project_id"] == "arch_docs"
    assert "Closing memory runtime..." in result.stderr
    assert "project_id not provided; using configured default 'arch_docs'." in result.stderr