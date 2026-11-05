"""Parsers for `uci -X show network|dhcp`, `network.interface dump`, `luci-rpc` leases and hints, `ip -j`."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Mapping
from typing import Any, Literal

from openwrtgui.net.model import (
    Address,
    DeviceConf,
    DhcpConf,
    DnsConf,
    Family,
    HostConf,
    InterfaceConf,
    InterfaceLive,
    Lease,
    LiveRoute,
    LiveRule,
    RouteConf,
    RuleConf,
)

ROUTE_KINDS: tuple[Literal["route", "route6"], ...] = ("route", "route6")
RULE_KINDS: tuple[Literal["rule", "rule6"], ...] = ("rule", "rule6")


def sections(uci: Mapping[str, str], config: str, type_: str) -> list[str]:
    """Section names of one type, in file order."""
    prefix = config + "."
    return [
        k[len(prefix) :] for k, v in uci.items() if k.startswith(prefix) and k.count(".") == 1 and v == type_
    ]


def options(uci: Mapping[str, str], config: str, section: str) -> dict[str, str]:
    prefix = f"{config}.{section}."
    return {
        k[len(prefix) :]: v for k, v in uci.items() if k.startswith(prefix) and "." not in k[len(prefix) :]
    }


def _int(value: str | None) -> int | None:
    return int(value) if value is not None and value.lstrip("-").isdigit() else None


def _prefix(netmask: str) -> int | None:
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen
    except ValueError:
        return None


def _address(ipaddr: str | None, netmask: str | None) -> Address | None:
    """`a.b.c.d/p`, or the old `ipaddr` + `netmask` pair; a list of addresses gives its first."""
    if not ipaddr:
        return None
    first = ipaddr.split()[0]
    ip, _, prefix = first.partition("/")
    if not prefix:
        if netmask is None:
            return None
        bits = _prefix(netmask)
        return Address(ip, bits) if bits is not None else None
    return Address(ip, int(prefix)) if prefix.isdigit() else None


def interfaces(uci: Mapping[str, str]) -> list[InterfaceConf]:
    out = []
    for name in sections(uci, "network", "interface"):
        o = options(uci, "network", name)
        out.append(
            InterfaceConf(
                name=name,
                proto=o.get("proto", "none"),
                device=o.get("device") or o.get("ifname"),
                address=_address(o.get("ipaddr"), o.get("netmask")),
                gateway=o.get("gateway"),
                dns=tuple(o.get("dns", "").split()),
                mtu=_int(o.get("mtu")),
                auto=o.get("auto", "1") != "0",
            )
        )
    return out


def devices(uci: Mapping[str, str]) -> list[DeviceConf]:
    out = []
    for section in sections(uci, "network", "device"):
        o = options(uci, "network", section)
        out.append(DeviceConf(section, o.get("name", ""), o.get("type"), tuple(o.get("ports", "").split())))
    return out


def _target(o: Mapping[str, str]) -> str:
    target = o.get("target", "")
    if target and "/" not in target and "netmask" in o:
        bits = _prefix(o["netmask"])
        return f"{target}/{bits}" if bits is not None else target
    return target


def routes(uci: Mapping[str, str]) -> list[RouteConf]:
    out = []
    for kind in ROUTE_KINDS:
        for section in sections(uci, "network", kind):
            o = options(uci, "network", section)
            out.append(
                RouteConf(
                    section=section,
                    kind=kind,
                    interface=o.get("interface"),
                    target=_target(o),
                    gateway=o.get("gateway"),
                    metric=_int(o.get("metric")),
                    table=o.get("table"),
                    type=o.get("type"),
                    disabled=o.get("disabled") == "1",
                )
            )
    return out


def rules(uci: Mapping[str, str]) -> list[RuleConf]:
    out = []
    for kind in RULE_KINDS:
        for section in sections(uci, "network", kind):
            o = options(uci, "network", section)
            out.append(
                RuleConf(
                    section=section,
                    kind=kind,
                    src=o.get("src"),
                    dest=o.get("dest"),
                    in_iface=o.get("in"),
                    out_iface=o.get("out"),
                    lookup=o.get("lookup"),
                    priority=_int(o.get("priority")),
                    action=o.get("action"),
                    disabled=o.get("disabled") == "1",
                )
            )
    return out


def dhcp_sections(uci: Mapping[str, str]) -> list[DhcpConf]:
    out = []
    for section in sections(uci, "dhcp", "dhcp"):
        o = options(uci, "dhcp", section)
        out.append(
            DhcpConf(
                section=section,
                interface=o.get("interface", section),
                enabled=o.get("ignore") != "1",
                start=_int(o.get("start")),
                limit=_int(o.get("limit")),
                leasetime=o.get("leasetime"),
                options=tuple(o.get("dhcp_option", "").split()),
                dhcpv6=o.get("dhcpv6"),
                ra=o.get("ra"),
            )
        )
    return out


def hosts(uci: Mapping[str, str]) -> list[HostConf]:
    out = []
    for section in sections(uci, "dhcp", "host"):
        o = options(uci, "dhcp", section)
        out.append(
            HostConf(
                section=section,
                name=o.get("name"),
                macs=tuple(m.lower() for m in o.get("mac", "").split()),
                ip=o.get("ip"),
                leasetime=o.get("leasetime"),
                gets_address=o.get("ignore") != "1",
            )
        )
    return out


def dnsmasq(uci: Mapping[str, str]) -> DnsConf | None:
    found = sections(uci, "dhcp", "dnsmasq")
    return DnsConf(found[0], options(uci, "dhcp", found[0])) if found else None


def parse_interface_dump(result: Mapping[str, Any]) -> list[InterfaceLive]:
    raw = [i for i in result.get("interface", []) if isinstance(i, dict) and i.get("interface")]
    l3 = {
        str(i.get("l3_device")): str(i["interface"])
        for i in raw
        if not i.get("dynamic") and i.get("l3_device")
    }
    names = {str(i["interface"]) for i in raw}
    out = []
    for i in raw:
        name = str(i["interface"])
        device = i.get("device") or i.get("l3_device")
        parent = None
        if i.get("dynamic"):
            stem = name.rsplit("_", 1)[0]
            parent = l3.get(str(device)) or (stem if stem != name and stem in names else None)
        out.append(
            InterfaceLive(
                name=name,
                up=bool(i.get("up")),
                proto=str(i.get("proto", "none")),
                device=str(device) if device else None,
                ipv4=tuple(Address(str(a["address"]), int(a["mask"])) for a in i.get("ipv4-address", [])),
                ipv6=tuple(f"{a['address']}/{a['mask']}" for a in i.get("ipv6-address", [])),
                dynamic=bool(i.get("dynamic")),
                parent=parent,
                uptime_s=_int(str(i["uptime"])) if "uptime" in i else None,
                errors=tuple(f"{e.get('subsystem', '')}: {e.get('code', '')}" for e in i.get("errors", [])),
            )
        )
    return out


def parse_leases(result: Mapping[str, Any]) -> list[Lease]:
    out = []
    for raw in result.get("dhcp_leases", []):
        out.append(
            Lease(
                4,
                str(raw["macaddr"]).lower() if raw.get("macaddr") else None,
                str(raw.get("ipaddr", "")),
                raw.get("hostname") or None,
                _int(str(raw["expires"])) if "expires" in raw else None,
            )
        )
    for raw in result.get("dhcp6_leases", []):
        ip = raw.get("ip6addr") or next(iter(raw.get("ip6addrs", [])), "")
        out.append(
            Lease(
                6,
                str(raw["macaddr"]).lower() if raw.get("macaddr") else None,
                str(ip),
                raw.get("hostname") or None,
                _int(str(raw["expires"])) if "expires" in raw else None,
            )
        )
    return out


def parse_host_hints(result: Mapping[str, Any]) -> dict[str, str]:
    """MAC (lower case) → the host's name, else its first IPv4 address."""
    out = {}
    for mac, hint in result.items():
        if not isinstance(hint, dict):
            continue
        label = hint.get("name") or next(iter(hint.get("ipaddrs", [])), None)
        if label:
            out[mac.lower()] = str(label)
    return out


def parse_ip_routes(text: str, family: Family) -> list[LiveRoute]:
    """`ip -j -<4|6> route show table all`; a JSON error raises ValueError."""
    return [
        LiveRoute(
            family=family,
            dst=str(r.get("dst", "")),
            gateway=r.get("gateway"),
            dev=r.get("dev"),
            table=str(r.get("table", "main")),
            proto=r.get("protocol"),
            metric=r.get("metric"),
            type=str(r.get("type", "unicast")),
        )
        for r in json.loads(text)
    ]


def parse_ip_rules(text: str, family: Family) -> list[LiveRule]:
    out = []
    for r in json.loads(text):
        src = r.get("src")
        if src and "srclen" in r:
            src = f"{src}/{r['srclen']}"
        out.append(LiveRule(family, int(r.get("priority", 0)), src, r.get("table")))
    return out


def parse_ssh_connection(text: str) -> tuple[str, str] | None:
    """`$SSH_CONNECTION` is `<client ip> <client port> <server ip> <server port>`: (PC, router) addresses."""
    parts = text.split()
    return (parts[0], parts[2]) if len(parts) >= 4 else None
