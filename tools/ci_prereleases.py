"""CI pre-releases (``vX.Y.Z-ci.N``) in build order.

Reads ``gh release list --json tagName,isPrerelease`` on stdin:

- ``newest``: prints the tag of the highest-numbered CI pre-release, or an empty line when there is none.
- ``beyond K``: prints the tags after the K highest-numbered, one per line, oldest first.

N is the CI run number, which grows with every run. GitHub's creation time is not the build order: a re-run
of an older master run publishes its build after a newer one. prerelease.yml compares a merge with the newest
build and keeps the ten newest. A list it cannot read exits non-zero and prints nothing, so the workflow
publishes, as before.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Mapping
from typing import Any

_CI_TAG = re.compile(r"-ci\.([0-9]+)$")


def run_number(release: Mapping[str, Any]) -> int | None:
    tag = release["tagName"]
    if not isinstance(tag, str):
        raise TypeError(f"tagName is not text: {tag!r}")
    match = _CI_TAG.search(tag)
    if release.get("isPrerelease") is not True or match is None:
        return None
    return int(match.group(1))


def in_build_order(releases: Iterable[Mapping[str, Any]]) -> list[str]:
    numbered = [(n, r["tagName"]) for r in releases if (n := run_number(r)) is not None]
    return [tag for _, tag in sorted(numbered)]


def newest(releases: Iterable[Mapping[str, Any]]) -> str:
    ordered = in_build_order(releases)
    return ordered[-1] if ordered else ""


def beyond(releases: Iterable[Mapping[str, Any]], keep: int) -> list[str]:
    ordered = in_build_order(releases)
    return ordered[: max(len(ordered) - keep, 0)]


def _releases(text: str) -> list[Mapping[str, Any]]:
    listed = json.loads(text)
    if not isinstance(listed, list) or not all(isinstance(r, dict) for r in listed):
        raise ValueError("not a list of releases")
    return listed


def main(argv: list[str]) -> int:
    keep: int | None
    if argv == ["newest"]:
        keep = None
    elif len(argv) == 2 and argv[0] == "beyond" and argv[1].isdigit():
        keep = int(argv[1])
    else:
        print("usage: ci_prereleases.py newest | beyond K", file=sys.stderr)
        return 2
    try:
        releases = _releases(sys.stdin.read())
        lines = [newest(releases)] if keep is None else beyond(releases, keep)
    except (ValueError, KeyError, TypeError) as error:
        print(f"ci_prereleases.py: cannot read the release list: {error}", file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
