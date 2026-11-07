"""`conntrack -L` flows, and a target's RTP ports read from them ("RTP ports come from conntrack")."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

NOT_RTP = frozenset({53, 67, 68, 123, 5060, 5061})  # DNS, DHCP, NTP, SIP


@dataclass(frozen=True)
class Flow:
    proto: str
    src: str
    dst: str
    sport: int
    dport: int


def parse_conntrack(text: str) -> list[Flow]:
    """The original direction of each flow (the first src/dst/sport/dport of its line)."""
    flows = []
    for line in text.splitlines():
        tokens = line.split()
        if not tokens or "=" in tokens[0]:
            continue
        first: dict[str, str] = {}
        for token in tokens[1:]:
            key, eq, value = token.partition("=")
            if eq and key in ("src", "dst", "sport", "dport") and key not in first:
                first[key] = value
        if len(first) == 4 and first["sport"].isdigit() and first["dport"].isdigit():
            sport, dport = int(first["sport"]), int(first["dport"])
            flows.append(Flow(tokens[0], first["src"], first["dst"], sport, dport))
    return flows


def rtp_ports(flows: Sequence[Flow], ip: str) -> tuple[int, ...]:
    """The target's side of its UDP flows, except flows of DNS, DHCP, NTP and SIP (either end's port)."""
    ports = set()
    for f in flows:
        if f.proto != "udp" or f.sport in NOT_RTP or f.dport in NOT_RTP:
            continue
        port = f.sport if f.src == ip else f.dport if f.dst == ip else None
        if port is not None:
            ports.add(port)
    return tuple(sorted(ports))
