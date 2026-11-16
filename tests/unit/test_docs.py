"""The project documents, issue forms and manual stay complete and link only to things that exist."""

from __future__ import annotations

import ast
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


def released_minors(changelog: str) -> list[str]:
    """The `x.y` of every released `## [x.y.z] - date` section, newest first, each once."""
    found = re.findall(r"^## \[(\d+\.\d+)\.\d+\] - \d{4}-\d{2}-\d{2}$", changelog, re.MULTILINE)
    return list(dict.fromkeys(found))


def test_readme_describes_every_released_minor() -> None:
    """0.7.0 shipped with a README that stopped at v0.6: the opening note names the newest release and every
    release has its "What vX.Y adds" section."""
    readme = _read(ROOT / "README.md")
    minors = released_minors(_read(ROOT / "CHANGELOG.md"))
    assert {"0.1", "0.6", "0.7"} <= set(minors)
    assert f"> v{minors[0]} adds " in readme, minors[0]
    assert "## What v0.1 does" in readme
    missing = [m for m in minors if m != "0.1" and f"## What v{m} adds" not in readme]
    assert missing == []


def test_readme_screenshots_are_ones_e2e_writes() -> None:
    shown = {
        t.removeprefix(SCREENSHOT_URL).removesuffix(".png")
        for t in _LINK.findall(_read(ROOT / "README.md"))
        if t.startswith(SCREENSHOT_URL)
    }
    assert {"wifi", "rf-live", "luci-page"} <= shown
    assert shown <= _screens()


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


def test_home_lists_every_sidebar_page() -> None:
    """v1.0a1 D8: the manual's home page links every page the sidebar has."""
    sidebar = {t for t in _LINK.findall(_read(MANUAL / "_Sidebar.md")) if not t.startswith("http")}
    home = set(_LINK.findall(_read(MANUAL / "Home.md")))
    assert sidebar - {"Home"} <= home, sorted(sidebar - home)
    assert "covers v0.4" not in _read(MANUAL / "Home.md")


def test_v1_0a2_pages_are_documented() -> None:
    system = _read(MANUAL / "System.md")
    wanted = ("## Plugins", "Configure in LuCI", "## Mount points", "block-mount", "Generate", "extroot")
    for text in wanted:
        assert text in system, text
    firewall = _read(MANUAL / "Firewall.md")
    assert "## Legacy iptables" in firewall and "filter table" in firewall
    assert "AP4" not in _read(MANUAL / "LuCI-pages.md")  # the simulator's router is not the user's


def test_v1_0a3_vlan_editor_is_documented() -> None:
    ports = _read(MANUAL / "Ports-and-VLANs.md")
    assert "## VLANs on a DSA router" in ports
    for words in ("60 s rollback", "may carry this app's SSH", "2 minutes", "power-cycle", "own-port lock"):
        assert words in ports, words
    assert "## A router that does not come back after a rollback" in _read(MANUAL / "Troubleshooting.md")
    assert "Switch/VLAN config opens the Ports screen" in _read(MANUAL / "LuCI-pages.md")
    released = _read(ROOT / "CHANGELOG.md").split("## [0.8.0]", 1)[1].split("## [", 1)[0]
    assert "bridge VLAN" in released  # shipped in 0.8.0
    assert "AP5" not in ports  # the simulator's router is not the user's


def test_no_manual_page_answers_for_v0_1() -> None:
    assert "Not in v0.1" not in _read(MANUAL / "FAQ.md")


_INTERNAL = re.compile(r"open item|\(O\d{1,2}\)|\bO\d{1,2}\b|txctl|AP2 recording|not built yet|not offered yet")
_TS_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _user_pages() -> dict[str, str]:
    return {p.stem: _read(p) for p in MANUAL.glob("*.md")}


def _python_strings(path: Path) -> list[str]:
    """String constants in a module, docstrings left out (they are for developers)."""
    tree = ast.parse(_read(path))
    docs = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
    ]


def test_manual_names_no_open_items_or_bench_sessions() -> None:
    """v1.0d D2: open-item numbers and the bench's own sessions mean nothing to a user."""
    found = [(page, m.group(0)) for page, text in _user_pages().items() for m in _INTERNAL.finditer(text)]
    assert found == []


def test_the_app_shows_no_open_items_or_bench_sessions() -> None:
    found = [
        (p.name, s)
        for p in (ROOT / "src" / "openwrtgui").rglob("*.py")
        for s in _python_strings(p)
        if _INTERNAL.search(s)
    ]
    for p in (ROOT / "frontend" / "src").rglob("*.ts*"):
        if ".test." in p.name or p.parent.name == "testing" or p.name == "schema.ts":
            continue
        found += [(p.name, m.group(0)) for m in _INTERNAL.finditer(_TS_COMMENT.sub("", _read(p)))]
    assert found == []


def test_bench_router_names_only_in_pictures_and_examples() -> None:
    """v1.0d D3: AP1/AP2 appear in screenshot alt text and `code` examples, not in sentences."""
    found = []
    for page, text in _user_pages().items():
        prose = _CODE_SPAN.sub("", _IMAGE.sub("", text))
        found += [(page, m.group(0)) for m in re.finditer(r"\bAP\d\b", prose)]
    assert found == []
