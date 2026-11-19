"""The GitHub workflows parse and keep the shape the release process relies on."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

GITHUB = Path(__file__).resolve().parents[2] / ".github"
WORKFLOWS = GITHUB / "workflows"
NAMES = ("ci.yml", "prerelease.yml", "release.yml", "wiki.yml", "codeql.yml", "security.yml")


def _load(path: Path) -> dict[Any, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), path
    return data


def _on(workflow: dict[Any, Any]) -> dict[str, Any]:
    # YAML 1.1 reads a bare `on:` key as the boolean True.
    trigger = workflow.get("on", workflow.get(True))
    assert isinstance(trigger, dict)
    return trigger


@pytest.mark.parametrize("name", NAMES)
def test_workflow_parses_with_jobs(name: str) -> None:
    workflow = _load(WORKFLOWS / name)
    assert workflow.get("name")
    assert _on(workflow)
    assert workflow["jobs"]


def test_ci_jobs_and_triggers() -> None:
    ci = _load(WORKFLOWS / "ci.yml")
    assert ci["name"] == "CI"
    assert set(ci["jobs"]) == {"changes", "python", "frontend", "e2e", "windows", "actionlint"}
    on = _on(ci)
    assert {"push", "pull_request", "workflow_call"} <= set(on)
    # a pull request runs once, on its own event, not again for the push to its branch
    assert on["push"]["branches"] == ["master"]
    assert ci["concurrency"]["cancel-in-progress"] is True
    assert set(ci["jobs"]["e2e"]["needs"]) == {"changes", "python", "frontend"}
    assert set(ci["jobs"]["windows"]["needs"]) == {"changes", "python", "frontend"}


def test_ci_runs_the_jobs_a_pull_request_needs() -> None:
    """Text only: the Python job (its tests read CHANGELOG, README and SECURITY.md). docs/manual: the frontend
    job too, since the app bundles the manual as its help. Anything else, a push or a release: every job."""
    jobs = _load(WORKFLOWS / "ci.yml")["jobs"]
    assert "needs" not in jobs["python"] and "if" not in jobs["python"]
    assert "if" not in jobs["actionlint"]
    assert set(jobs["frontend"]["needs"]) == {"changes", "python"}
    assert jobs["frontend"]["if"] == "needs.changes.outputs.scope != 'text'"
    for name in ("e2e", "windows"):
        assert jobs[name]["if"] == "needs.changes.outputs.scope == 'full'"
    changes = jobs["changes"]
    assert changes["outputs"]["scope"] == "${{ steps.scope.outputs.scope }}"
    assert changes["steps"][0]["with"]["fetch-depth"] == 2  # the pull request's merge commit and its base
    run = next(s["run"] for s in changes["steps"] if s.get("id") == "scope")
    assert "tools/ci_scope.py" in run
    assert "--no-renames" in run  # a file moved out of src/ lists its old path too
    assert "pull_request" in run and "scope=full" in run


def test_text_only_pull_requests_skip_the_audits_and_codeql() -> None:
    for name in ("security.yml", "codeql.yml"):
        on = _on(_load(WORKFLOWS / name))
        assert on["pull_request"]["paths-ignore"] == ["**.md", "docs/**"]
        # CodeQL compares a pull request with master's analysis, so every push to master is analysed
        assert on["push"]["branches"] == ["master"] and "paths-ignore" not in on["push"]


def test_prerelease_follows_successful_ci_on_master() -> None:
    pre = _load(WORKFLOWS / "prerelease.yml")
    run = _on(pre)["workflow_run"]
    assert run["workflows"] == ["CI"]
    assert run["types"] == ["completed"]
    assert run["branches"] == ["master"]
    assert pre["permissions"]["contents"] == "write"
    condition = pre["jobs"]["ships"]["if"]
    assert "conclusion == 'success'" in condition and "event == 'push'" in condition


def test_prerelease_skips_a_merge_of_text_only() -> None:
    """A merge that changes only text the app never ships publishes no CI build: the Pre-release channel would
    offer an update that changes nothing, and push an older build out of the ten kept."""
    jobs = _load(WORKFLOWS / "prerelease.yml")["jobs"]
    ships = jobs["ships"]
    assert ships["outputs"]["ships"] == "${{ steps.ships.outputs.ships }}"
    assert ships["steps"][0]["with"]["fetch-depth"] == 0  # the last CI pre-release's commit and its tag
    run = next(s["run"] for s in ships["steps"] if s.get("id") == "ships")
    assert "tools/ci_scope.py" in run and "--no-renames" in run
    assert jobs["prerelease"]["needs"] == "ships"
    assert jobs["prerelease"]["if"] == "needs.ships.outputs.ships == 'true'"


def test_release_runs_on_version_tags_after_tests() -> None:
    release = _load(WORKFLOWS / "release.yml")
    assert _on(release)["push"]["tags"] == ["v[0-9]+.[0-9]+.[0-9]+"]
    assert release["jobs"]["tests"]["uses"] == "./.github/workflows/ci.yml"
    assert release["jobs"]["release"]["needs"] == "tests"


def test_codeql_languages() -> None:
    codeql = _load(WORKFLOWS / "codeql.yml")
    matrix = codeql["jobs"]["analyze"]["strategy"]["matrix"]
    assert sorted(matrix["language"]) == ["javascript-typescript", "python"]
    assert "schedule" in _on(codeql)


def test_dependabot_ecosystems() -> None:
    bot = _load(GITHUB / "dependabot.yml")
    seen = {(u["package-ecosystem"], u["directory"]) for u in bot["updates"]}
    assert seen == {("uv", "/"), ("npm", "/frontend"), ("github-actions", "/")}
    assert all(u["schedule"]["interval"] == "weekly" for u in bot["updates"])


def test_security_audits_block_on_shipped_packages() -> None:
    """v1.0b1 D10: shipped packages block, build tools advise, and none of it can stop a release."""
    sec = _load(WORKFLOWS / "security.yml")
    assert {"push", "pull_request", "schedule"} <= set(_on(sec))
    # pip-audit skips requirements whose markers are false where it runs; the installer ships the win32 ones
    assert sec["jobs"]["python-deps"]["runs-on"] == "windows-latest"
    assert sec["permissions"] == {"contents": "read"}
    steps = {s["name"]: s for job in sec["jobs"].values() for s in job["steps"] if "name" in s}
    py = steps["Shipped Python packages"]
    assert "pip-audit" in py["run"] and "--extra build" in py["run"] and "continue-on-error" not in py
    ui = steps["Shipped UI packages"]
    assert ui["run"].strip() == "npm audit --omit=dev --audit-level=high" and "continue-on-error" not in ui
    assert steps["Build and test tools (advisory)"]["continue-on-error"] is True
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "pip-audit" not in ci and "npm audit" not in ci
    project = tomllib.loads((GITHUB.parent / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert any(d.startswith("pip-audit") for d in project["optional-dependencies"]["dev"])
