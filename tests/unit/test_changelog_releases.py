"""Every released section of CHANGELOG.md renders as release notes the way release.yml writes them
(`tools/release_notes.py <version> --out`): not empty, no U+FFFD, every `###` heading of the section kept, and
the version's link at the bottom of the file (PR #62 review: no test looked at a released section)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "release_notes.py"
CHANGELOG = ROOT / "CHANGELOG.md"
_RELEASED = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", re.MULTILINE)
_REPO = "https://github.com/dm17ryk/OpenWrtGUI/"


def released(text: str) -> list[str]:
    return _RELEASED.findall(text)


def _headings(text: str, version: str) -> list[str]:
    """The `###` headings between the version's heading and the next `## [` one, read without the tool."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"## [{version}] "))
    out = []
    for line in lines[start + 1 :]:
        if line.startswith("## ["):
            break
        if line.startswith("### "):
            out.append(line)
    return out


def note_problems(changelog: Path, version: str, out: Path) -> list[str]:
    """What is wrong with the version's release notes, as release.yml would publish them."""
    text = changelog.read_text(encoding="utf-8")
    run = subprocess.run(
        [sys.executable, str(SCRIPT), version, "--changelog", str(changelog), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    if run.returncode != 0:
        return [f"release_notes.py exited {run.returncode}: {run.stderr.strip()}"]
    notes = out.read_bytes().decode("utf-8", errors="replace")
    problems = []
    if not notes.strip():
        problems.append("the notes are empty")
    if "�" in notes:
        problems.append("the notes hold U+FFFD")
    problems += [f"the notes lost {h!r}" for h in _headings(text, version) if h not in notes.splitlines()]
    link = re.compile(
        rf"^\[{re.escape(version)}\]: {re.escape(_REPO)}(?:releases/tag/v{re.escape(version)}|compare/\S+)$",
        re.MULTILINE,
    )
    if not link.search(text):
        problems.append(f"no [{version}] link at the bottom")
    return problems


def test_the_changelog_has_its_releases() -> None:
    versions = released(CHANGELOG.read_text(encoding="utf-8"))
    assert {"0.1.0", "0.6.0", "0.7.0"} <= set(versions)


@pytest.mark.parametrize("version", released(CHANGELOG.read_text(encoding="utf-8")))
def test_every_released_section_renders_as_its_release_notes(version: str, tmp_path: Path) -> None:
    assert note_problems(CHANGELOG, version, tmp_path / "dist" / "notes.md") == []


GOOD = """# Changelog

## [Unreleased]

## [0.2.0] - 2026-11-12

Two things.

### Added

- System › LEDs.

### Fixed

- A fix.

## [0.1.0] - 2026-11-10

### Added

- The start.

[Unreleased]: https://github.com/dm17ryk/OpenWrtGUI/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.2.0
[0.1.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.1.0
"""


def test_a_good_changelog_passes(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(GOOD, encoding="utf-8")
    assert [note_problems(changelog, v, tmp_path / f"{v}.md") for v in released(GOOD)] == [[], []]


@pytest.mark.parametrize(
    ("broken", "problem"),
    [
        (
            GOOD.replace("Two things.\n\n### Added\n\n- System › LEDs.\n\n### Fixed\n\n- A fix.\n", ""),
            "empty",
        ),
        (GOOD.replace("- System › LEDs.", "- System � LEDs."), "U+FFFD"),
        (GOOD.replace("[0.2.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.2.0\n", ""), "link"),
        # a line that reads as a link definition ends the notes early: the Fixed heading never reaches them
        (
            GOOD.replace("- System › LEDs.", "- System › LEDs.\n[see]: https://example.org"),
            "lost '### Fixed'",
        ),
        (GOOD.replace("## [0.2.0] - 2026-11-12", "## [0.2] - 2026-11-12"), "exited 1"),  # no 0.2.0 section
    ],
)
def test_a_broken_section_is_caught(broken: str, problem: str, tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(broken, encoding="utf-8")
    found = note_problems(changelog, "0.2.0", tmp_path / "notes.md")
    assert any(problem in p for p in found), found
