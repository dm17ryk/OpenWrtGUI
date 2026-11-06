"""DNS (spec 7.4, the LuCI DNS page): dnsmasq's forwarders, local domain, rebind protection, per-domain
overrides and switches, plus any other option of its section. A plain `dhcp` apply with a dnsmasq reload."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from openwrtgui.net.model import DnsConf
from openwrtgui.uci import UciOp

DNS_SWITCHES = (
    "domainneeded",
    "boguspriv",
    "localise_queries",
    "logqueries",
    "localservice",
    "rebind_protection",
    "rebind_localhost",
)
HAND_LAID = frozenset({"server", "domain", "local", "rebind_domain", "address", "cachesize", *DNS_SWITCHES})
_DOMAIN = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_OPTION = re.compile(r"^[a-z0-9_]+$")
CACHE_MAX = 10000


@dataclass(frozen=True)
class DnsRequest:
    forwarders: tuple[str, ...] | None = None
    domain: str | None = None  # "" removes the local domain
    rebind_domains: tuple[str, ...] | None = None
    overrides: tuple[tuple[str, str], ...] | None = None  # (host, ip) → address='/host/ip'
    switches: Mapping[str, bool] = field(default_factory=dict)
    cachesize: int | Literal["default"] | None = None  # "default" removes it (dnsmasq's default applies)
    others: Mapping[str, str | None] = field(default_factory=dict)  # None removes the option


def _ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def _server(text: str) -> str:
    """`IP`, `IP#port` or `/domain/IP`, as dnsmasq's `server` takes them."""
    value = text.strip()
    rest = value
    if value.startswith("/"):
        _, domain, rest = (value.split("/", 2) + ["", ""])[:3]
        if not _DOMAIN.match(domain):
            rest = ""
    ip, _, port = rest.partition("#")
    if not _ip(ip) or (port and not (port.isdigit() and 0 < int(port) < 65536)):
        raise ValueError(f"{text} is not a DNS server (IP, IP#port or /domain/IP)")
    return value


def _domain(text: str) -> str:
    if not _DOMAIN.match(text):
        raise ValueError(f"{text} is not a domain name")
    return text


def _list(path: str, items: tuple[str, ...]) -> list[UciOp]:
    return [UciOp("delete", path), *(UciOp("add_list", path, item) for item in items)]


def compile_dns(req: DnsRequest, dns: DnsConf | None) -> list[UciOp]:
    if dns is None:
        raise ValueError("This router has no dnsmasq section")
    p = f"dhcp.{dns.section}"
    ops: list[UciOp] = []
    if req.domain is not None:
        if req.domain:
            ops += [
                UciOp("set", f"{p}.local", f"/{_domain(req.domain)}/"),
                UciOp("set", f"{p}.domain", req.domain),
            ]
        else:
            ops += [UciOp("delete", f"{p}.local"), UciOp("delete", f"{p}.domain")]
    if req.forwarders is not None:
        ops += _list(f"{p}.server", tuple(_server(s) for s in req.forwarders))
    if req.rebind_domains is not None:
        ops += _list(f"{p}.rebind_domain", tuple(_domain(d) for d in req.rebind_domains))
    if req.overrides is not None:
        items = []
        for host, ip in req.overrides:
            if not _ip(ip.strip()):
                raise ValueError(f"{ip} is not an IP address")
            items.append(f"/{_domain(host.strip())}/{ip.strip()}")
        ops += _list(f"{p}.address", tuple(items))
    for name, on in req.switches.items():
        if name not in DNS_SWITCHES:
            raise ValueError(f"{name} is not a DNS switch")
        ops.append(UciOp("set", f"{p}.{name}", "1" if on else "0"))
    if req.cachesize == "default":
        ops.append(UciOp("delete", f"{p}.cachesize"))
    elif req.cachesize is not None:
        if not 0 <= req.cachesize <= CACHE_MAX:
            raise ValueError(f"Cache size is 0 to {CACHE_MAX}")
        ops.append(UciOp("set", f"{p}.cachesize", str(req.cachesize)))
    for name, value in req.others.items():
        if not _OPTION.match(name):
            raise ValueError(f"{name} is not an option name")
        if name in HAND_LAID:
            raise ValueError(f"Use the {name} control for {name}")
        ops.append(UciOp("delete", f"{p}.{name}") if value is None else UciOp("set", f"{p}.{name}", value))
    return ops
