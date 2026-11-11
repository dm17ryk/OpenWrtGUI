"""Print the CHANGELOG.md section of one version, for the GitHub release notes.

Usage: python tools/release_notes.py 0.1.0 --out notes.md   (exit 1 when the version has no section)
Without --out the notes go to stdout, in UTF-8 whatever the console's code page.
"""

from __future__ import annotations

import argparse
import io
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
    ap.add_argument("--out", type=Path, help="write the notes to this file (UTF-8) instead of stdout")
    args = ap.parse_args(argv)
    notes = section(args.version, args.changelog.read_text(encoding="utf-8"))
    if notes is None:
        print(f"release_notes: no '## [{args.version}]' section in {args.changelog}", file=sys.stderr)
        return 1
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes((notes + "\n").encode("utf-8"))
        return 0
    if isinstance(sys.stdout, io.TextIOWrapper):
        # piped on a Windows runner, stdout is the ANSI code page: "›" and "—" reached the notes as U+FFFD
        sys.stdout.reconfigure(encoding="utf-8")
    print(notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
