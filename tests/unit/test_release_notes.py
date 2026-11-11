"""tools/release_notes.py prints one version's section of CHANGELOG.md."""

from __future__ import annotations

import os
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


def test_notes_are_utf8_whatever_the_console_encoding(tmp_path: Path) -> None:
    """The release job pipes the notes into a UTF-8 file on a Windows runner, where a piped Python writes the
    ANSI code page: every "›" in the 0.4.0-0.6.0 release notes was published as U+FFFD."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        CHANGELOG.replace("- Bench Guard.", "- System › Access, keys — and LEDs."), encoding="utf-8"
    )
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}  # the runner's piped stdout
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "0.1.0", "--changelog", str(changelog)],
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "- System › Access, keys — and LEDs.".encode() in result.stdout


def test_out_writes_the_notes_file_as_utf8(tmp_path: Path) -> None:
    """The release job writes the notes file through --out: no console encoding or shell pipe in between."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG.replace("- Bench Guard.", "- System › LEDs."), encoding="utf-8")
    out = tmp_path / "dist" / "notes.md"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "0.1.0", "--changelog", str(changelog), "--out", str(out)],
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == b""
    assert (
        out.read_bytes() == "### Added\n\n- Dashboard with the 2.4 GHz air map.\n- System › LEDs.\n".encode()
    )


def test_version_is_matched_exactly(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG.replace("## [0.0.9]", "## [0.1.01]"), encoding="utf-8")
    assert _notes("0.1.0", changelog).stdout.strip().endswith("- Bench Guard.")
    assert _notes("0.1", changelog).returncode == 1
