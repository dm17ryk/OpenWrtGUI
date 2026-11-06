"""Traffic rules, port forwards (redirect), NAT rules and IP sets as uci operations (spec 7.6, LuCI tabs)."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from openwrtgui.fw.compile import check_others, require_fw4
from openwrtgui.fw.model import FwRuleConf, IpsetConf, NatConf, RedirectConf
from openwrtgui.fw.parse import IPSET_FIELDS, NAT_FIELDS, REDIRECT_FIELDS, RULE_FIELDS
from openwrtgui.fw.state import PIN_DHCP, PIN_SSH, FirewallState
from openwrtgui.uci import UciOp

Kind = Literal["rule", "redirect", "nat", "ipset"]
LABEL = {"rule": "rule", "redirect": "port forward", "nat": "NAT rule", "ipset": "IP set"}
LETTER = {"rule": "r", "redirect": "p", "nat": "n", "ipset": "s"}
PINNED = {PIN_SSH: "Allow SSH from this PC", PIN_DHCP: "Allow DHCP and DNS"}
PROTOS = frozenset({"all", "tcp", "udp", "icmp", "icmpv6", "igmp", "esp", "ah", "sctp", "udplite", "gre"})
MATCHES = frozenset(
    {"src_ip", "dest_ip", "src_net", "dest_net", "src_mac", "dest_mac", "src_port", "dest_port"}
)
_NAME = re.compile(r"[A-Za-z0-9 ._-]{1,64}")
_SET_NAME = re.compile(r"[A-Za-z0-9_]{1,31}")
_PORT = re.compile(r"\d{1,5}(-\d{1,5})?")
_MAC = re.compile(r"[0-9a-f]{2}(:[0-9a-f]{2}){5}")
_ICMP = re.compile(r"[a-z0-9-]{1,40}")


@dataclass(frozen=True)
class RuleRequest:
    section: str | None
    name: str
    src: str | None
    dest: str | None
    proto: str | None
    src_ip: tuple[str, ...] = ()
    dest_ip: tuple[str, ...] = ()
    src_port: str | None = None
    dest_port: str | None = None
    icmp_type: tuple[str, ...] = ()
    family: Literal["ipv4", "ipv6", "any"] = "any"
    target: Literal["ACCEPT", "REJECT", "DROP"] = "ACCEPT"
    enabled: bool = True
    others: Mapping[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class ForwardRequest:
    section: str | None
    name: str
    src: str = "wan"
    src_dport: str = ""
    dest: str = "lan"
    dest_ip: str = ""
    dest_port: str | None = None
    proto: str = "tcp udp"
    enabled: bool = True
    others: Mapping[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class NatRequest:
    section: str | None
    name: str
    src: str
    src_ip: str | None
    dest_ip: str | None
    dest_port: str | None
    proto: str | None
    target: Literal["SNAT", "MASQUERADE", "ACCEPT"]
    snat_ip: str | None = None
    snat_port: str | None = None
    enabled: bool = True
    others: Mapping[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class IpsetRequest:
    section: str | None
    name: str
    family: Literal["ipv4", "ipv6"]
    match: tuple[str, ...]
    entries: tuple[str, ...]
    enabled: bool = True
    others: Mapping[str, str | None] = field(default_factory=dict)


SectionRequest = RuleRequest | ForwardRequest | NatRequest | IpsetRequest


# ------------------------------------------------------------------ checks
def check_name(name: str) -> None:
    if not _NAME.fullmatch(name):
        raise ValueError("A name is 1 to 64 letters, digits, spaces, '.', '-' or '_'")


def check_ports(text: str) -> str:
    if not all(_PORT.fullmatch(p) and all(0 < int(x) < 65536 for x in p.split("-")) for p in text.split()):
        raise ValueError(f"{text} is not a port or range (e.g. 80 or 8000-8080)")
    return text


def check_address(text: str) -> str:
    try:
        ipaddress.ip_network(text, strict=False)
    except ValueError:
        raise ValueError(f"{text} is not an IPv4 address or network") from None
    if "\n" in text:
        raise ValueError(f"{text} is not an IPv4 address or network")
    return text


def check_mac(text: str) -> str:
    mac = text.strip().lower().replace("-", ":")
    if not _MAC.fullmatch(mac):
        raise ValueError(f"{text} is not a MAC address")
    return mac


def check_proto(text: str) -> str:
    for p in text.split():
        if p not in PROTOS and not (p.isdigit() and 0 <= int(p) <= 255):
            raise ValueError(f"{p} is not a protocol (tcp, udp, icmp, all, …)")
    return text


def _zone(name: str | None, zones: set[str]) -> str | None:
    if name is not None and name != "*" and name not in zones:
        raise ValueError(f"There is no zone named {name}")
    return name


def _entry(match: str, text: str) -> str:
    if match.endswith("_mac"):
        return check_mac(text)
    if match.endswith("_port"):
        return check_ports(text)
    return check_address(text)


# ------------------------------------------------------------------ options per kind
def _rule(r: RuleRequest, zones: set[str]) -> tuple[dict[str, str | None], dict[str, tuple[str, ...]]]:
    if r.icmp_type and not all(_ICMP.fullmatch(t) for t in r.icmp_type):
        raise ValueError(f"{' '.join(r.icmp_type)} is not an ICMP type")
    scalars: dict[str, str | None] = {
        "src": _zone(r.src, zones),
        "dest": _zone(r.dest, zones),
        "proto": check_proto(r.proto) if r.proto else None,
        "src_port": check_ports(r.src_port) if r.src_port else None,
        "dest_port": check_ports(r.dest_port) if r.dest_port else None,
        "family": None if r.family == "any" else r.family,
        "target": r.target,
    }
    lists = {
        "src_ip": tuple(check_address(a) for a in r.src_ip),
        "dest_ip": tuple(check_address(a) for a in r.dest_ip),
        "icmp_type": r.icmp_type,
    }
    return scalars, lists


def _redirect(r: ForwardRequest, zones: set[str]) -> tuple[dict[str, str | None], dict[str, tuple[str, ...]]]:
    return {
        "src": _zone(r.src, zones),
        "src_dport": check_ports(r.src_dport),
        "dest": _zone(r.dest, zones),
        "dest_ip": check_address(r.dest_ip),
        "dest_port": check_ports(r.dest_port) if r.dest_port else None,
        "proto": check_proto(r.proto),
        "target": "DNAT",
    }, {}


def _nat(r: NatRequest, zones: set[str]) -> tuple[dict[str, str | None], dict[str, tuple[str, ...]]]:
    if r.target == "SNAT" and not r.snat_ip:
        raise ValueError("SNAT needs a Rewrite to address")
    return {
        "src": _zone(r.src, zones),
        "src_ip": check_address(r.src_ip) if r.src_ip else None,
        "dest_ip": check_address(r.dest_ip) if r.dest_ip else None,
        "dest_port": check_ports(r.dest_port) if r.dest_port else None,
        "proto": check_proto(r.proto) if r.proto else None,
        "target": r.target,
        "snat_ip": check_address(r.snat_ip) if r.snat_ip else None,
        "snat_port": check_ports(r.snat_port) if r.snat_port else None,
    }, {}


def _ipset(r: IpsetRequest) -> tuple[dict[str, str | None], dict[str, tuple[str, ...]]]:
    if not r.match or any(m not in MATCHES for m in r.match):
        raise ValueError(f"Match is one or more of {', '.join(sorted(MATCHES))}")
    return {"family": r.family}, {
        "match": r.match,
        "entry": tuple(_entry(r.match[0], e) for e in r.entries),
    }


def _options(
    kind: Kind, r: SectionRequest, zones: set[str]
) -> tuple[dict[str, str | None], dict[str, tuple[str, ...]]]:
    if isinstance(r, RuleRequest):
        return _rule(r, zones)
    if isinstance(r, ForwardRequest):
        return _redirect(r, zones)
    if isinstance(r, NatRequest):
        return _nat(r, zones)
    return _ipset(r)


FIELDS: dict[Kind, frozenset[str]] = {
    "rule": RULE_FIELDS,
    "redirect": REDIRECT_FIELDS,
    "nat": NAT_FIELDS,
    "ipset": IPSET_FIELDS,
}


def _existing(kind: Kind, state: FirewallState) -> dict[str, str | None]:
    """section → name of every section of this kind."""
    conf = state.conf
    rows: Sequence[FwRuleConf | RedirectConf | NatConf | IpsetConf]
    if kind == "rule":
        rows = conf.rules
    elif kind == "redirect":
        rows = conf.redirects
    elif kind == "nat":
        rows = conf.nats
    else:
        rows = conf.ipsets
    return {x.section: x.name for x in rows}


def _refuse_pinned(section: str | None) -> None:
    if section in PINNED:
        raise ValueError(f"{PINNED[section]} is kept open by the app; change it on Zones and model")


def compile_sections(
    kind: Kind, upserts: Sequence[SectionRequest], deletes: Sequence[str], state: FirewallState
) -> list[UciOp]:
    require_fw4(state)
    existing = _existing(kind, state)
    zones = {z.name for z in state.conf.zones}
    for section in deletes:
        _refuse_pinned(section)
        if section not in existing:
            raise ValueError(f"There is no {LABEL[kind]} {section}")
    names = {name for section, name in existing.items() if name and section not in deletes}
    ops: list[UciOp] = []
    new = 0
    for r in upserts:
        _refuse_pinned(r.section)
        if r.section is not None and r.section not in existing:
            raise ValueError(f"There is no {LABEL[kind]} {r.section}")
        if kind == "ipset":
            if not _SET_NAME.fullmatch(r.name):
                raise ValueError("An IP set name is 1 to 31 letters, digits or _")
        else:
            check_name(r.name)
        was = existing.get(r.section) if r.section else None
        if r.name != was and r.name in names:
            raise ValueError(f"There is already a {LABEL[kind]} named {r.name}")
        names.add(r.name)
        check_others(r.others, FIELDS[kind])
        scalars, lists = _options(kind, r, zones)
        if r.section is None:
            new += 1
            p = f"firewall.${LETTER[kind]}{new}"
            ops.append(UciOp("add", p, kind))
        else:
            p = f"firewall.{r.section}"
        ops.append(UciOp("set", f"{p}.name", r.name))
        for k, v in scalars.items():
            ops.append(UciOp("delete", f"{p}.{k}") if v is None else UciOp("set", f"{p}.{k}", v))
        for k, items in lists.items():
            ops += [UciOp("delete", f"{p}.{k}"), *(UciOp("add_list", f"{p}.{k}", i) for i in items)]
        ops.append(UciOp("delete", f"{p}.enabled") if r.enabled else UciOp("set", f"{p}.enabled", "0"))
        ops += [
            UciOp("delete", f"{p}.{k}") if v is None else UciOp("set", f"{p}.{k}", v)
            for k, v in r.others.items()
        ]
    ops += [UciOp("delete", f"firewall.{s}") for s in deletes]
    return ops


def expectations(
    kind: Kind, upserts: Sequence[SectionRequest], deletes: Sequence[str], state: FirewallState
) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    """(fw4 rule names, IP set names) each with whether it must be in fw4's ruleset after the change."""
    existing = _existing(kind, state)
    gone = [(name, False) for s, name in existing.items() if s in deletes and name]
    asked = [(r.name, r.enabled) for r in upserts]
    if kind == "ipset":
        return [], [*asked, *gone]
    return [*asked, *gone], []
