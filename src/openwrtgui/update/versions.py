"""Release versions: X.Y.Z, CI pre-releases X.Y.Z-ci.N, and dev builds X.Y.Z-dev."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(?:ci\.(\d+)|(dev)))?$")


@functools.total_ordering
@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int
    ci: int | None
    dev: bool = False

    def _key(self) -> tuple[int, int, int, int, int]:
        if self.dev:
            return (self.major, self.minor, self.patch, 0, -1)
        if self.ci is not None:
            return (self.major, self.minor, self.patch, 0, self.ci)
        return (self.major, self.minor, self.patch, 1, 0)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.dev:
            return f"{base}-dev"
        return f"{base}-ci.{self.ci}" if self.ci is not None else base


def parse_version(tag: str) -> Version:
    m = _TAG.match(tag.strip())
    if not m:
        raise ValueError(f"not a release version: {tag!r}")
    return Version(int(m[1]), int(m[2]), int(m[3]), int(m[4]) if m[4] else None, dev=bool(m[5]))
