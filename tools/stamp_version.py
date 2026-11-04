"""Write a build's version into src/openwrtgui/version.py and print its numeric Windows form.

Usage: python tools/stamp_version.py 0.1.0-ci.42  ->  APP_VERSION = "0.1.0-ci.42", prints 0.1.0.42

The version must be BASE_VERSION, BASE_VERSION-dev or BASE_VERSION-ci.N. The numeric form
X.Y.Z.N (N = CI run number, 0 otherwise) goes into the exe and installer version info.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VERSION_PY = Path(__file__).resolve().parents[1] / "src" / "openwrtgui" / "version.py"
_VERSION = re.compile(r"^(?P<base>\d+\.\d+\.\d+)(?:-dev|-ci\.(?P<run>\d+))?$")
_BASE_LINE = re.compile(r'^BASE_VERSION = "(?P<base>[^"]+)"$', re.MULTILINE)
_APP_LINE = re.compile(r'^APP_VERSION = "[^"]*"$', re.MULTILINE)


def stamp(version: str, path: Path) -> str:
    """Rewrite APP_VERSION in `path`; return the numeric X.Y.Z.N. Raises ValueError when refused."""
    match = _VERSION.match(version)
    if match is None:
        raise ValueError(f"{version!r} is not X.Y.Z, X.Y.Z-dev or X.Y.Z-ci.N")
    text = path.read_text(encoding="utf-8")
    base = _BASE_LINE.search(text)
    if base is None or not _APP_LINE.search(text):
        raise ValueError(f"{path} has no BASE_VERSION / APP_VERSION lines")
    if match["base"] != base["base"]:
        raise ValueError(f"{version} does not start with BASE_VERSION {base['base']}")
    path.write_text(_APP_LINE.sub(f'APP_VERSION = "{version}"', text), encoding="utf-8", newline="\n")
    return f"{match['base']}.{match['run'] or 0}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version")
    ap.add_argument("--file", type=Path, default=VERSION_PY)
    args = ap.parse_args(argv)
    try:
        print(stamp(args.version, args.file))
    except ValueError as exc:
        print(f"stamp_version: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
