"""What a router can do for faults, read once per router: the nft families that filter bridged traffic
(`nft -c` is nft's check mode and commits nothing), netem's distribution tables, kernel modules, tools."""

from __future__ import annotations

CONNTRACK_UDP = "conntrack -L -p udp"
TC_TABLES = "ls /usr/lib/tc"
MODULES = "ls /lib/modules/$(uname -r)"
# one name per `command -v`: busybox ash prints only the first of several (AP2, 2026-11-07)
TOOLS = 'for c in start-stop-daemon setsid timeout tcpdump conntrack fw4; do command -v "$c"; done'


def _check(table: str) -> str:
    return f"nft -c -f /dev/stdin <<'OWG'\n{table}\nOWG"


# netdev first: hooks on the target's own device see bridged and routed traffic alike. nft wants a newline
# or ';' between the chain's '}' and the table's (AP2, 2026-11-07: "} }" is a syntax error).
FAMILY_CHECKS: dict[str, str] = {
    "netdev": _check(
        'table netdev owgcheck { chain c { type filter hook egress device "br-lan" priority -500; }; }'
    ),
    "bridge": _check("table bridge owgcheck { chain c { type filter hook prerouting priority -300; }; }"),
}

CAPABILITY_READS = (CONNTRACK_UDP, TC_TABLES, MODULES, TOOLS)
