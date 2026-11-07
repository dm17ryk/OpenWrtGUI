"""The `firewall` uci config as fw4 reads it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Policy = Literal["ACCEPT", "REJECT", "DROP"]
Direction = Literal["input", "forward", "output"]
DIRECTIONS: tuple[Direction, ...] = ("input", "forward", "output")


@dataclass(frozen=True)
class DefaultsConf:
    section: str
    values: dict[str, str]


@dataclass(frozen=True)
class ZoneConf:
    section: str
    name: str
    networks: tuple[str, ...]
    input: Policy
    output: Policy
    forward: Policy
    masq: bool
    mtu_fix: bool
    others: dict[str, str] = field(default_factory=dict)

    def policy(self, direction: Direction) -> Policy:
        return {"input": self.input, "forward": self.forward, "output": self.output}[direction]


@dataclass(frozen=True)
class ForwardingConf:
    section: str
    src: str | None
    dest: str | None
    enabled: bool


@dataclass(frozen=True)
class FwRuleConf:
    section: str
    name: str | None
    src: str | None
    dest: str | None
    proto: str | None
    src_ip: tuple[str, ...]
    dest_ip: tuple[str, ...]
    src_port: str | None
    dest_port: str | None
    icmp_type: tuple[str, ...]
    family: str | None
    target: str
    enabled: bool
    others: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RedirectConf:
    section: str
    name: str | None
    src: str | None
    src_dport: str | None
    dest: str | None
    dest_ip: str | None
    dest_port: str | None
    proto: str | None
    target: str
    enabled: bool
    others: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NatConf:
    section: str
    name: str | None
    src: str | None
    src_ip: str | None
    dest_ip: str | None
    dest_port: str | None
    proto: str | None
    target: str
    snat_ip: str | None
    snat_port: str | None
    enabled: bool
    others: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class IpsetConf:
    section: str
    name: str | None
    family: str
    match: tuple[str, ...]
    entries: tuple[str, ...]
    enabled: bool
    others: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class IncludeConf:
    section: str
    type: str | None
    path: str | None
    position: str | None


@dataclass(frozen=True)
class FirewallConf:
    defaults: DefaultsConf | None
    zones: tuple[ZoneConf, ...]
    forwardings: tuple[ForwardingConf, ...]
    rules: tuple[FwRuleConf, ...]
    redirects: tuple[RedirectConf, ...]
    nats: tuple[NatConf, ...]
    ipsets: tuple[IpsetConf, ...]
    includes: tuple[IncludeConf, ...]

    def zone(self, name: str | None) -> ZoneConf | None:
        return next((z for z in self.zones if z.name == name), None)
