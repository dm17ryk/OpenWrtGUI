"""Print the CHANGELOG.md section of one version, for the GitHub release notes.

Usage: python tools/release_notes.py 0.1.0 > notes.md   (exit 1 when the version has no section)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
_NEXT_SECTION = re.compile(r"^## \[")
_LINK_DEFINITION = re.compile(r"^\[[^\]]+\]: ")


def section(version: str, text: str) -> str | None:
    """The body under '## [version]' up to the next version heading or the link definitions."""
    heading = re.compile(rf"^## \[{re.escape(version)}\](?:\s|$)")
    body: list[str] | None = None
    for line in text.splitlines():
        if body is None:
            if heading.match(line):
                body = []
            continue
        if _NEXT_SECTION.match(line) or _LINK_DEFINITION.match(line):
            break
        body.append(line)
    return None if body is None else "\n".join(body).strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("version")
    ap.add_argument("--changelog", type=Path, default=CHANGELOG)
    args = ap.parse_args(argv)
    notes = section(args.version, args.changelog.read_text(encoding="utf-8"))
    if notes is None:
        print(f"release_notes: no '## [{args.version}]' section in {args.changelog}", file=sys.stderr)
        return 1
    print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
