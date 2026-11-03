"""Who the router is: /etc/openwrt_release and `ubus call system board`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_LINE = re.compile(r"^([A-Z_]+)=['\"]?(.*?)['\"]?$")


@dataclass(frozen=True)
class Identity:
    hostname: str
    model: str
    board_name: str
    distribution: str
    version: str
    revision: str
    target: str


def parse_release(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _LINE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def build_identity(release: dict[str, str], board: dict[str, Any]) -> Identity:
    rel = board.get("release", {})
    return Identity(
        hostname=str(board.get("hostname", "")),
        model=str(board.get("model", "")),
        board_name=str(board.get("board_name", "")),
        distribution=str(rel.get("distribution") or release.get("DISTRIB_ID", "")),
        version=str(rel.get("version") or release.get("DISTRIB_RELEASE", "")),
        revision=str(rel.get("revision") or release.get("DISTRIB_REVISION", "")),
        target=str(rel.get("target") or release.get("DISTRIB_TARGET", "")),
    )
