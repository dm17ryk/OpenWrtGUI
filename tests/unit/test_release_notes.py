"""tools/release_notes.py prints one version's section of CHANGELOG.md."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "release_notes.py"

CHANGELOG = """# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

- Nothing yet.

## [0.1.0] - 2026-11-10

### Added

- Dashboard with the 2.4 GHz air map.
- Bench Guard.

## [0.0.9] - 2026-10-01

- Older notes.

[0.1.0]: https://github.com/dm17ryk/OpenWrtGUI/releases/tag/v0.1.0
"""


def _notes(version: str, changelog: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), version, "--changelog", str(changelog)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_prints_only_the_requested_section(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    result = _notes("0.1.0", changelog)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "### Added\n\n- Dashboard with the 2.4 GHz air map.\n- Bench Guard."


def test_missing_version_exits_1(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    result = _notes("0.2.0", changelog)
    assert result.returncode == 1
    assert "0.2.0" in result.stderr
    assert result.stdout == ""


def test_version_is_matched_exactly(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG.replace("## [0.0.9]", "## [0.1.01]"), encoding="utf-8")
    assert _notes("0.1.0", changelog).stdout.strip().endswith("- Bench Guard.")
    assert _notes("0.1", changelog).returncode == 1
