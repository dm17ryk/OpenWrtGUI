"""Parsers for `swconfig dev <switch> show|help|get arl_table`, `/proc/net/arp` and the uci switch sections.

`show` puts MIB counters under `mib:` on lines without a leading tab; only tab-indented lines are attributes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from openwrtgui.net.parse import options, sections
from openwrtgui.ports.model import (
    Members,
    SwitchConf,
    SwitchHelp,
    SwitchLive,
    SwitchPortConf,
    SwitchPortLive,
    SwitchVlanConf,
    SwitchVlanLive,
)

_BLOCK = re.compile(r"^(Global attributes|Port (\d+)|VLAN (\d+)):$")
_HEAD = re.compile(r"ports: (\d+)(?: \(cpu @ (\d+)\))?, vlans: (\d+)")
_ATTR = re.compile(r"Attribute \d+ \([^)]*\): (\S+)")
_ARL = re.compile(r"port\s*(\d+):\s*mac\s*([0-9a-f]{2}(?::[0-9a-f]{2}){5})", re.IGNORECASE)
_MAC = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")


def _int(value: str | None) -> int | None:
    return int(value) if value is not None and value.isdigit() else None


def parse_members(text: str) -> Members:
    """`0 1 2 3 6t` → ((0, False), …, (6, True)), ascending."""
    out = []
    for token in text.split():
        num = token.rstrip("t*u")
        if num.isdigit():
            out.append((int(num), token.endswith("t")))
    return tuple(sorted(out))


def render_members(members: Mapping[int, bool]) -> str:
    return " ".join(f"{p}{'t' if tagged else ''}" for p, tagged in sorted(members.items()))


def _blocks(text: str) -> list[tuple[str, dict[str, str]]]:
    blocks: list[tuple[str, dict[str, str]]] = []
    for line in text.splitlines():
        head = _BLOCK.match(line.strip()) if not line.startswith("\t") else None
        if head:
            blocks.append((head.group(1), {}))
        elif line.startswith("\t") and blocks:
            key, sep, value = line.strip().partition(":")
            if sep:
                blocks[-1][1][key.strip()] = value.strip()
    return blocks


def _port(num: int, attrs: Mapping[str, str]) -> SwitchPortLive:
    link = attrs.get("link", "")
    up = "link:up" in link
    speed = re.search(r"speed:(\d+)", link) if up else None
    duplex = None if not up else True if "full-duplex" in link else False if "half-duplex" in link else None
    enable = attrs.get("enable")
    return SwitchPortLive(
        num=num,
        enabled=True if enable == "1" else False if enable == "0" else None,
        pvid=_int(attrs.get("pvid")),
        link=up,
        speed_mbps=int(speed.group(1)) if speed else None,
        full_duplex=duplex,
        mirror_rx=attrs.get("enable_mirror_rx") == "1",
        mirror_tx=attrs.get("enable_mirror_tx") == "1",
    )


def parse_swconfig_show(name: str, text: str) -> SwitchLive:
    enable_vlan: bool | None = None
    monitor: int | None = None
    ports: list[SwitchPortLive] = []
    vlans: list[SwitchVlanLive] = []
    for head, attrs in _blocks(text):
        if head == "Global attributes":
            enable_vlan = attrs["enable_vlan"] == "1" if "enable_vlan" in attrs else None
            monitor = _int(attrs.get("mirror_monitor_port"))
        elif head.startswith("Port "):
            ports.append(_port(int(head.split()[1]), attrs))
        else:
            vlans.append(
                SwitchVlanLive(
                    int(head.split()[1]), _int(attrs.get("vid")), parse_members(attrs.get("ports", ""))
                )
            )
    return SwitchLive(name, enable_vlan, monitor, tuple(ports), tuple(vlans))


def parse_swconfig_help(text: str) -> SwitchHelp:
    head = _HEAD.search(text)
    port_attrs: set[str] = set()
    global_attrs: set[str] = set()
    target: set[str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "--switch":
            target = global_attrs
        elif stripped in ("--vlan", "--port"):
            target = port_attrs if stripped == "--port" else None
        elif (attr := _ATTR.search(stripped)) and target is not None:
            target.add(attr.group(1))
    return SwitchHelp(
        ports=int(head.group(1)) if head else 0,
        cpu_port=_int(head.group(2)) if head else None,
        vlans=int(head.group(3)) if head else 0,
        port_attrs=frozenset(port_attrs),
        global_attrs=frozenset(global_attrs),
    )


def parse_arl(text: str) -> dict[str, int]:
    """MAC → switch port, from `get arl_table` lines `Port <n>: MAC <mac>`; any other format gives nothing."""
    return {m.group(2).lower(): int(m.group(1)) for m in _ARL.finditer(text)}


def parse_arp(text: str) -> dict[str, str]:
    """`/proc/net/arp`: IP → MAC (lower case); incomplete entries (flags 0x0) are left out."""
    out = {}
    for line in text.splitlines()[1:]:
        cols = line.split()
        if len(cols) >= 4 and cols[2] != "0x0" and _MAC.match(cols[3].lower()):
            out[cols[0]] = cols[3].lower()
    return out


def switch_conf(uci: Mapping[str, str], name: str) -> SwitchConf | None:
    for section in sections(uci, "network", "switch"):
        o = options(uci, "network", section)
        if o.get("name") == name:
            return SwitchConf(section, name, _int(o.get("mirror_monitor_port")))
    return None


def switch_vlans(uci: Mapping[str, str]) -> list[SwitchVlanConf]:
    out = []
    for section in sections(uci, "network", "switch_vlan"):
        o = options(uci, "network", section)
        out.append(
            SwitchVlanConf(
                section,
                o.get("device", ""),
                _int(o.get("vlan")) or 0,
                _int(o.get("vid")),
                parse_members(o.get("ports", "")),
            )
        )
    return out


def switch_ports(uci: Mapping[str, str]) -> list[SwitchPortConf]:
    out = []
    for section in sections(uci, "network", "switch_port"):
        o = options(uci, "network", section)
        port = _int(o.get("port"))
        if port is not None:
            out.append(
                SwitchPortConf(
                    section,
                    o.get("device", ""),
                    port,
                    o.get("enable_mirror_rx") == "1",
                    o.get("enable_mirror_tx") == "1",
                )
            )
    return out
