"""tools/ci_prereleases.py: CI pre-releases ordered by their run number, not by when GitHub created them."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "ci_prereleases.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_prereleases", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ci(*runs: int) -> list[dict[str, Any]]:
    return [{"tagName": f"v1.1.0-ci.{n}", "isPrerelease": True} for n in runs]


def test_the_newest_is_the_highest_run_not_the_last_created() -> None:
    """A re-run of an older master run publishes its build after a newer one: GitHub lists it first."""
    assert _module().newest(_ci(7, 8, 6)) == "v1.1.0-ci.8"


def test_run_numbers_compare_as_numbers() -> None:
    assert _module().newest(_ci(9, 10)) == "v1.1.0-ci.10"


def test_only_ci_prereleases_count() -> None:
    releases = [
        {"tagName": "v1.1.0", "isPrerelease": False},
        {"tagName": "v1.1.0-ci.99", "isPrerelease": False},
        {"tagName": "v1.2.0-rc.1", "isPrerelease": True},
        {"tagName": "v1.1.0-ci.9x", "isPrerelease": True},
        *_ci(5, 4),
    ]
    assert _module().newest(releases) == "v1.1.0-ci.5"


def test_no_ci_prerelease_gives_no_tag() -> None:
    assert _module().newest([]) == ""
    assert _module().newest([{"tagName": "v1.1.0", "isPrerelease": False}]) == ""


def test_beyond_keeps_the_highest_runs() -> None:
    """The ten kept are the ten newest builds, even when an older one was published last."""
    releases = _ci(7, 12, 11, 10, 9, 8, 6, 5, 4, 3, 2, 1)
    assert _module().beyond(releases, 10) == ["v1.1.0-ci.1", "v1.1.0-ci.2"]
    assert _module().beyond(releases, 12) == []


def _run(*args: str, stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args], input=stdin, capture_output=True, text=True
    )


def test_the_script_reads_the_release_list_from_stdin() -> None:
    listed = json.dumps(_ci(7, 8, 6))
    assert _run("newest", stdin=listed).stdout == "v1.1.0-ci.8\n"
    assert _run("newest", stdin="[]").stdout == "\n"
    assert _run("beyond", "1", stdin=listed).stdout == "v1.1.0-ci.6\nv1.1.0-ci.7\n"


@pytest.mark.parametrize("stdin", ["", "not json", '{"message": "Bad credentials"}', '[{"tagName": 1}]'])
def test_an_unreadable_list_fails_so_the_workflow_publishes(stdin: str) -> None:
    done = _run("newest", stdin=stdin)
    assert done.returncode != 0
    assert done.stdout == ""


@pytest.mark.parametrize("args", [[], ["oldest"], ["beyond"], ["beyond", "ten"], ["beyond", "-1"]])
def test_a_wrong_command_fails(args: list[str]) -> None:
    done = _run(*args, stdin="[]")
    assert done.returncode != 0
    assert done.stdout == ""
