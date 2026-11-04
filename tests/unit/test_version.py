import json
import re
import tomllib
from pathlib import Path

from openwrtgui.version import APP_VERSION, BASE_VERSION

ROOT = Path(__file__).resolve().parents[2]


def test_base_version_is_semver() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", BASE_VERSION)


def test_app_version_starts_with_base() -> None:
    assert APP_VERSION.startswith(BASE_VERSION)


def test_package_files_carry_the_base_version() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    iss = (ROOT / "installer" / "OpenWrtGUI.iss").read_text(encoding="utf-8")
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == BASE_VERSION
    # CI installs with `uv sync --frozen`, which never refreshes a stale lock.
    assert next(p for p in lock["package"] if p["name"] == "openwrtgui")["version"] == BASE_VERSION
    assert package["version"] == BASE_VERSION
    assert f'#define AppVersion "{BASE_VERSION}-dev"' in iss
    assert f'#define AppNumVersion "{BASE_VERSION}.0"' in iss
