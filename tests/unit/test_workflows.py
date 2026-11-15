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
    assert set(ci["jobs"]) == {"python", "frontend", "e2e", "windows", "actionlint"}
    assert {"push", "pull_request", "workflow_call"} <= set(_on(ci))
    assert ci["concurrency"]["cancel-in-progress"] is True
    assert set(ci["jobs"]["e2e"]["needs"]) == {"python", "frontend"}
    assert set(ci["jobs"]["windows"]["needs"]) == {"python", "frontend"}


def test_prerelease_follows_successful_ci_on_master() -> None:
    pre = _load(WORKFLOWS / "prerelease.yml")
    run = _on(pre)["workflow_run"]
    assert run["workflows"] == ["CI"]
    assert run["types"] == ["completed"]
    assert run["branches"] == ["master"]
    assert pre["permissions"]["contents"] == "write"


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
