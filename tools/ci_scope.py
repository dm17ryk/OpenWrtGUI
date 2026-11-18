"""Which CI jobs a change needs, from the paths it changes (one per line on stdin, as `git diff --name-only`).

Prints one word:

- ``text``: only text the app never ships: Markdown at the top level or under .github/, and docs/ outside
  docs/manual. The Python job still runs: its tests read CHANGELOG.md, README.md and SECURITY.md.
- ``manual``: docs/manual too, which the frontend bundles as the in-app help: the frontend job runs as well.
- ``full``: anything else, or no readable path: every job.

The text paths are listed here, not the code paths, so a path nobody thought of runs every job. ci.yml uses it
for pull requests; prerelease.yml publishes no CI build when a merge changes only text.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable

TEXT, MANUAL, FULL = "text", "manual", "full"
_ORDER = (TEXT, MANUAL, FULL)


def path_scope(path: str) -> str:
    if path.startswith("docs/manual/"):
        return MANUAL
    if path.startswith("docs/"):
        return TEXT
    top_level = "/" not in path
    if path.endswith(".md") and (top_level or path.startswith(".github/")):
        return TEXT
    return FULL


def scope(paths: Iterable[str]) -> str:
    seen = {path_scope(p.strip()) for p in paths if p.strip()}
    if not seen:
        return FULL
    return max(seen, key=_ORDER.index)


def main() -> None:
    print(scope(sys.stdin.read().splitlines()))


if __name__ == "__main__":
    main()
