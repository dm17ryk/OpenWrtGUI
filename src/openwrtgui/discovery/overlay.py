"""Busybox `ls -ldn` listings of /overlay/upper and /rom, kept as data whatever the names hold."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

_LS = re.compile(r"(\S{10})\s+\d+\s+\d+\s+\d+\s+(?:(\d+)|(\d+),\s*(\d+))\s+\w{3}\s+\d+\s+[\d:]+\s(/.*)")

Kind = Literal["file", "link", "whiteout", "other"]


class OverlayEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    kind: Kind
    size: int
    mode: str
    target: str | None = None


def mode_bits(mode: str) -> int:
    """`-rwxr-xr-x` → 0o755 (setuid, setgid and sticky shown as s, S, t, T)."""
    bits = 0
    for at, (char, value) in enumerate(zip(mode[1:10], (0o400, 0o200, 0o100) * 3, strict=False)):
        if char not in "-ST":
            bits |= value
        if char.lower() in "st" and at in (2, 5, 8):
            bits |= {2: 0o4000, 5: 0o2000, 8: 0o1000}[at]
    return bits


def parse_ls_ldn(text: str, root: str) -> tuple[tuple[OverlayEntry, ...], int]:
    """The entries under `root` (paths made relative to it) and how many lines could not be read."""
    entries: list[OverlayEntry] = []
    unreadable = 0
    prefix = root.rstrip("/") + "/"
    for line in text.splitlines():
        if not line.strip():
            continue
        found = _LS.fullmatch(line.strip(" "))
        if not found or not found.group(5).startswith(prefix):
            unreadable += 1
            continue
        mode, size, major, minor, path = found.groups()
        target: str | None = None
        if mode[0] == "l" and " -> " in path:
            path, target = path.split(" -> ", 1)
        if mode[0] == "-":
            kind: Kind = "file"
        elif mode[0] == "l":
            kind = "link"
        elif mode[0] == "c" and (major, minor) == ("0", "0"):
            kind = "whiteout"
        else:
            kind = "other"
        entries.append(
            OverlayEntry(
                path="/" + path[len(prefix) :], kind=kind, size=int(size or 0), mode=mode, target=target
            )
        )
    return tuple(entries), unreadable
