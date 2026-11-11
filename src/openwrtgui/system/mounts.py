"""System › Mount points, read-only (v0.6c plan D8): what is mounted and how full it is."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

_OCTAL = re.compile(r"\\([0-7]{3})")


class Mount(BaseModel):
    model_config = ConfigDict(frozen=True)

    device: str
    target: str
    fstype: str
    options: str


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True)

    filesystem: str
    size_kib: int
    used_kib: int
    available_kib: int
    use_pct: int
    target: str


def _unescape(field: str) -> str:
    """The kernel writes a space in a path as \\040 (and tab, newline, backslash likewise)."""
    return _OCTAL.sub(lambda m: chr(int(m.group(1), 8)), field)


def parse_mounts(text: str) -> list[Mount]:
    out: list[Mount] = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        out.append(
            Mount(
                device=_unescape(fields[0]), target=_unescape(fields[1]), fstype=fields[2], options=fields[3]
            )
        )
    return out


def parse_df(text: str) -> list[Usage]:
    """busybox `df -k`: Filesystem, 1K-blocks, Used, Available, Use%, Mounted on."""
    out: list[Usage] = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 6 or not fields[4].endswith("%"):
            continue
        try:
            size, used, available, pct = (int(fields[1]), int(fields[2]), int(fields[3]), int(fields[4][:-1]))
        except ValueError:
            continue
        out.append(
            Usage(
                filesystem=fields[0],
                size_kib=size,
                used_kib=used,
                available_kib=available,
                use_pct=pct,
                target=" ".join(fields[5:]),
            )
        )
    return out
