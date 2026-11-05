"""What the Network & DHCP screen reads: uci sections and their live state, as frozen values."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Literal

Family = Literal[4, 6]
BARE = {
    4: "Write the address with its prefix, e.g. 192.168.1.2/24 (a bare address becomes /32 on this image)",
    6: "Write the address with its prefix, e.g. fd00::1/64",
}


@dataclass(frozen=True)
class Address:
    ip: str
    prefix: int

    def __str__(self) -> str:
        return f"{self.ip}/{self.prefix}"


def parse_cidr(text: str, family: Family = 4) -> Address:
    """`address/prefix`; a bare address is refused because this image reads it as /32."""
    text = text.strip()
    refusal = ValueError(f"{text} is not an IPv{family} network (address/prefix)")
    if "/" not in text:
        try:
            bare = ipaddress.ip_address(text).version == family
        except ValueError:
            bare = False
        raise ValueError(BARE[family]) if bare else refusal
    try:
        iface = ipaddress.ip_interface(text)
    except ValueError:
        raise refusal from None
    if iface.version != family:
        raise refusal
    return Address(str(iface.ip), iface.network.prefixlen)


@dataclass(frozen=True)
class InterfaceConf:
    name: str
    proto: str
    device: str | None
    address: Address | None
    gateway: str | None
    dns: tuple[str, ...]
    mtu: int | None
    auto: bool


@dataclass(frozen=True)
class DeviceConf:
    section: str
    name: str
    type: str | None
    ports: tuple[str, ...]


@dataclass(frozen=True)
class InterfaceLive:
    name: str
    up: bool
    proto: str
    device: str | None
    ipv4: tuple[Address, ...]
    ipv6: tuple[str, ...]
    dynamic: bool
    parent: str | None
    uptime_s: int | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class RouteConf:
    section: str
    kind: Literal["route", "route6"]
    interface: str | None
    target: str
    gateway: str | None
    metric: int | None
    table: str | None
    type: str | None
    disabled: bool


@dataclass(frozen=True)
class RuleConf:
    section: str
    kind: Literal["rule", "rule6"]
    src: str | None
    dest: str | None
    in_iface: str | None
    out_iface: str | None
    lookup: str | None
    priority: int | None
    action: str | None
    disabled: bool


@dataclass(frozen=True)
class LiveRoute:
    family: Family
    dst: str
    gateway: str | None
    dev: str | None
    table: str
    proto: str | None
    metric: int | None
    type: str


@dataclass(frozen=True)
class LiveRule:
    family: Family
    priority: int
    src: str | None
    lookup: str | None


@dataclass(frozen=True)
class DhcpConf:
    section: str
    interface: str
    enabled: bool
    start: int | None
    limit: int | None
    leasetime: str | None
    options: tuple[str, ...]
    dhcpv6: str | None
    ra: str | None


@dataclass(frozen=True)
class HostConf:
    section: str
    name: str | None
    macs: tuple[str, ...]
    ip: str | None
    leasetime: str | None
    gets_address: bool


@dataclass(frozen=True)
class DnsConf:
    section: str
    values: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Lease:
    family: Family
    mac: str | None
    ip: str
    hostname: str | None
    expires_s: int | None
