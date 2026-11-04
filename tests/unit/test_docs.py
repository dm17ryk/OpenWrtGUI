"""The project documents, issue forms and manual stay complete and link only to things that exist."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MANUAL = ROOT / "docs" / "manual"
FORMS = ROOT / ".github" / "ISSUE_TEMPLATE"
SCREENSHOT_URL = "https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/"
_LINK = re.compile(r"\]\(([^)\s]+)\)")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _screens() -> set[str]:
    """Screenshot names that frontend/e2e/screenshots.spec.ts writes (and the wiki workflow publishes)."""
    spec = _read(ROOT / "frontend" / "e2e" / "screenshots.spec.ts")
    return set(re.findall(r"\['([a-z-]+)', '/", spec))


@pytest.mark.parametrize("name", ["bug.yml", "feature.yml", "router-support.yml"])
def test_issue_form_has_name_and_body(name: str) -> None:
    form = yaml.safe_load(_read(FORMS / name))
    assert form["name"]
    assert form["description"]
    assert isinstance(form["body"], list) and form["body"]


def test_router_support_form_asks_for_the_self_description() -> None:
    form = _read(FORMS / "router-support.yml")
    for wanted in ("ubus call system board", "/etc/board.json", "iw phy", "router-support"):
        assert wanted in form


def test_blank_issues_are_off() -> None:
    config = yaml.safe_load(_read(FORMS / "config.yml"))
    assert config["blank_issues_enabled"] is False
    assert config["contact_links"]


def test_readme_links_the_project_files() -> None:
    readme = _read(ROOT / "README.md")
    for target in ("ROADMAP.md", "CONTRIBUTING.md", "LICENSE"):
        assert f"]({target})" in readme, target
    assert SCREENSHOT_URL + "dashboard.png" in readme


def test_every_sidebar_page_exists() -> None:
    pages = [t for t in _LINK.findall(_read(MANUAL / "_Sidebar.md")) if not t.startswith("http")]
    assert len(pages) >= 10
    for page in pages:
        assert (MANUAL / f"{page}.md").is_file(), page


def test_manual_links_and_screenshots_resolve() -> None:
    screens = _screens()
    assert {"dashboard", "settings", "terminal"} <= screens
    for page in MANUAL.glob("*.md"):
        for target in _LINK.findall(_read(page)):
            if target.startswith(SCREENSHOT_URL):
                name = target.removeprefix(SCREENSHOT_URL).removesuffix(".png")
                assert name in screens, (page.name, target)
            elif not target.startswith(("http", "#", "mailto:")):
                assert (MANUAL / f"{target.split('#')[0]}.md").is_file(), (page.name, target)


def test_changelog_has_the_release_section() -> None:
    changelog = _read(ROOT / "CHANGELOG.md")
    assert "## [Unreleased]" in changelog
    assert "## [0.1.0]" in changelog
    notes = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "release_notes.py"), "0.1.0"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Bench Guard" in notes.stdout


def test_roadmap_has_every_milestone() -> None:
    roadmap = _read(ROOT / "ROADMAP.md")
    for milestone in ("v0.1 Foundation", "v0.2", "v0.3", "v0.4", "v0.5", "v0.6", "v0.7", "v1.0", "1.x"):
        assert milestone in roadmap, milestone


def test_agents_file_carries_the_bench_rules() -> None:
    agents = _read(ROOT / "AGENTS.md")
    assert "192.168.1.2" in agents
    assert "never type" in agents
    assert _read(ROOT / "CLAUDE.md").strip() == "See AGENTS.md."


def test_repo_files_exist() -> None:
    for name in ("SECURITY.md", "CODE_OF_CONDUCT.md", ".github/PULL_REQUEST_TEMPLATE.md"):
        assert (ROOT / name).is_file(), name
