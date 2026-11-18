"""tools/ci_scope.py: which CI jobs a change needs, from the paths it changes."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "ci_scope.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_scope", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_text_that_never_ships_needs_the_python_job_only() -> None:
    paths = [
        "CHANGELOG.md",
        "README.md",
        "SECURITY.md",
        "docs/superpowers/plans/2026-11-18-plan.md",
        "docs/design/screen.png",
        ".github/pull_request_template.md",
    ]
    assert _module().scope(paths) == "text"


def test_the_manual_is_bundled_as_the_in_app_help() -> None:
    assert _module().scope(["docs/manual/Updating.md", "CHANGELOG.md"]) == "manual"
    assert _module().scope(["docs/manual/Settings.md"]) == "manual"


@pytest.mark.parametrize(
    "path",
    [
        "src/openwrtgui/app.py",
        "src/openwrtgui/notes.md",  # Markdown inside the app may ship
        "frontend/src/App.tsx",
        "frontend/README.md",
        "tests/unit/test_docs.py",
        "tools/build_windows.ps1",
        "installer/OpenWrtGUI.iss",
        ".github/workflows/ci.yml",
        ".github/dependabot.yml",
        "pyproject.toml",
        "uv.lock",
        "LICENSE",
        "docs",  # not a file under docs/
        '"docs/manual/\\320\\220.md"',  # a path git had to quote: not read as the manual
    ],
)
def test_anything_else_runs_every_job(path: str) -> None:
    assert _module().scope(["README.md", "docs/manual/Install.md", path]) == "full"


@pytest.mark.parametrize("paths", [[], [""], ["  ", "\t"]])
def test_no_readable_path_runs_every_job(paths: list[str]) -> None:
    assert _module().scope(paths) == "full"


def test_the_script_reads_paths_from_stdin() -> None:
    def run(stdin: str) -> str:
        done = subprocess.run(
            [sys.executable, "-I", str(SCRIPT)], input=stdin, capture_output=True, text=True, check=True
        )
        return done.stdout

    assert run("README.md\ndocs/manual/Install.md\n") == "manual\n"
    assert run("CHANGELOG.md\r\n") == "text\n"
    assert run("README.md\nsrc/openwrtgui/app.py\n") == "full\n"
    assert run("") == "full\n"
