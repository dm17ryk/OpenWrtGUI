"""Traffic control: `tc qdisc show` text, netem parameters, u32 address matches as tc shows them."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Literal

_QDISC = re.compile(r"^qdisc (\S+) (\S+) dev (\S+) (root|parent (\S+))\s*(.*)$")
_TIME = re.compile(r"^\d+(\.\d+)?(us|ms|s)$")


@dataclass(frozen=True)
class Qdisc:
    dev: str
    kind: str
    handle: str
    parent: str | None
    root: bool
    params: str


def parse_qdiscs(text: str) -> list[Qdisc]:
    out = []
    for line in text.splitlines():
        if m := _QDISC.match(line.strip()):
            kind, handle, dev, where, parent, params = m.groups()
            out.append(Qdisc(dev, kind, handle, parent, where == "root", params.strip()))
    return out


def parse_netem(params: str) -> dict[str, str]:
    """`delay`, `jitter`, `distribution`, `loss`, `duplicate`, `reorder` as tc shows them."""
    tokens = params.split()
    out: dict[str, str] = {}
    for i, token in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if token == "delay" and nxt:
            out["delay"] = nxt
            if i + 2 < len(tokens) and _TIME.match(tokens[i + 2]):
                out["jitter"] = tokens[i + 2]
        elif token in ("distribution", "loss", "duplicate", "reorder") and nxt:
            out[token] = nxt
    return out


def u32_match(ip: str, field: Literal["src", "dst"]) -> str:
    """How `tc filter show` lists `match ip src|dst <ip>/32`."""
    return f"{int(ipaddress.IPv4Address(ip)):08x}/ffffffff at {12 if field == 'src' else 16}"
