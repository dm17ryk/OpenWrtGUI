"""tools/stamp_version.py rewrites APP_VERSION and prints the numeric Windows version."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from openwrtgui.version import BASE_VERSION

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "stamp_version.py"
VERSION_PY = ROOT / "src" / "openwrtgui" / "version.py"
# A version.py of its own, so these tests stay put when the real version moves on.
FAKE_VERSION_PY = '"""Version of this build."""\n\nBASE_VERSION = "1.4.0"\nAPP_VERSION = "1.4.0-dev"\n'


def _fake(tmp_path: Path) -> Path:
    target = tmp_path / "version.py"
    target.write_text(FAKE_VERSION_PY, encoding="utf-8")
    return target


def _stamp(version: str, target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), version, "--file", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_ci_version_is_written_and_numeric_form_printed(tmp_path: Path) -> None:
    target = _fake(tmp_path)
    result = _stamp("1.4.0-ci.42", target)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1.4.0.42"
    text = target.read_text(encoding="utf-8")
    assert 'APP_VERSION = "1.4.0-ci.42"' in text
    assert 'BASE_VERSION = "1.4.0"' in text


def test_release_and_dev_versions_get_run_number_zero(tmp_path: Path) -> None:
    target = _fake(tmp_path)
    assert _stamp("1.4.0", target).stdout.strip() == "1.4.0.0"
    assert 'APP_VERSION = "1.4.0"' in target.read_text(encoding="utf-8")
    assert _stamp("1.4.0-dev", target).stdout.strip() == "1.4.0.0"


def test_version_outside_base_is_refused(tmp_path: Path) -> None:
    target = _fake(tmp_path)
    before = target.read_text(encoding="utf-8")
    result = _stamp("1.5.0", target)
    assert result.returncode != 0
    assert "BASE_VERSION" in result.stderr
    assert target.read_text(encoding="utf-8") == before


def test_malformed_version_is_refused(tmp_path: Path) -> None:
    target = _fake(tmp_path)
    for bad in ("1.4.0-ci.", "1.4.0-beta", "1.4.0.1", "v1.4.0"):
        assert _stamp(bad, target).returncode != 0, bad


def test_the_real_version_file_takes_a_ci_version(tmp_path: Path) -> None:
    target = tmp_path / "version.py"
    target.write_text(VERSION_PY.read_text(encoding="utf-8"), encoding="utf-8")
    result = _stamp(f"{BASE_VERSION}-ci.7", target)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{BASE_VERSION}.7"
    assert f'APP_VERSION = "{BASE_VERSION}-ci.7"' in target.read_text(encoding="utf-8")
